from __future__ import annotations

import math

import numpy as np

from thermo0d.config.constants import CombCol, CombDurationMode, CombStartMode, ConnCol, ConnectionType, FeatureCol, VolumeCol
from thermo0d.model.free_piston.geometry import cylinder_distance_from_tdc, cylinder_volume_from_position, free_piston_equivalent_linear_kinematics, free_piston_is_compression_stroke, free_piston_local_cycle_angle_deg
from thermo0d.model.free_piston.thermo import pressure_from_state
from thermo0d.physics.kinematics import reference_theta_and_zero, wrap_angle_deg
from thermo0d.physics.openings import connection_area_and_coefficients
from thermo0d.physics.composition import unburned_mass_kg
from thermo0d.physics.quellen_props import lambda_from_air_and_fuel_mass, properties_from_mass_energy_components_quellen


F_COMB = int(FeatureCol.COMBUSTION)
FUELING_FIXED = 0
FUELING_SLOT_CLOSE = 1
FUELING_VAPOR_INJECTOR = 2
HCCI_IGNITION_GENERIC_LIVENGOOD_WU = 0
HCCI_IGNITION_BECK_2003_1_ARRHENIUS = 1
HCCI_IGNITION_BECK_2003_TWO_STAGE = 2
HCCI_IGNITION_TABULATED_LIVENGOOD_WU = 3


def _interp_axis_index_weight(axis: np.ndarray, value: float) -> tuple[int, int, float]:
    n = int(axis.shape[0])
    if n <= 1:
        return 0, 0, 0.0
    x = float(value)
    if x <= float(axis[0]):
        return 0, 0, 0.0
    if x >= float(axis[n - 1]):
        return n - 1, n - 1, 0.0
    hi = int(np.searchsorted(axis, x, side='right'))
    lo = max(hi - 1, 0)
    span = max(float(axis[hi] - axis[lo]), 1.0e-30)
    return lo, hi, (x - float(axis[lo])) / span


def _tabulated_hcci_ignition_delay_s(table, *, temp_K: float, pressure_Pa: float, lam: float, residual_fraction: float) -> float:
    if table is None:
        return 1.0e9
    temperature_axis = table["temperature_K"]
    pressure_axis = table["pressure_bar"]
    lambda_axis = table["lambda"]
    egr_axis = table["egr_rate"]
    delay_grid = table["delay_s"]
    egr_value = float(residual_fraction)
    if int(egr_axis.shape[0]) > 0 and float(egr_axis[-1]) > 1.5:
        egr_value *= 100.0
    indices = (
        _interp_axis_index_weight(temperature_axis, float(temp_K)),
        _interp_axis_index_weight(pressure_axis, float(pressure_Pa) * 1.0e-5),
        _interp_axis_index_weight(lambda_axis, float(lam)),
        _interp_axis_index_weight(egr_axis, egr_value),
    )
    value = 0.0
    for i0, wi in ((indices[0][0], 1.0 - indices[0][2]), (indices[0][1], indices[0][2])):
        for i1, wj in ((indices[1][0], 1.0 - indices[1][2]), (indices[1][1], indices[1][2])):
            for i2, wk in ((indices[2][0], 1.0 - indices[2][2]), (indices[2][1], indices[2][2])):
                for i3, wl in ((indices[3][0], 1.0 - indices[3][2]), (indices[3][1], indices[3][2])):
                    weight = wi * wj * wk * wl
                    if weight > 0.0:
                        value += weight * float(delay_grid[i0, i1, i2, i3])
    return max(float(value), 1.0e-9)


def _hcci_charge_o2_percent(air_mass_kg: float, burned_mass_kg: float, reference_o2_percent: float) -> float:
    charge_gas_mass_kg = max(float(air_mass_kg) + max(float(burned_mass_kg), 0.0), 1.0e-18)
    return max(float(reference_o2_percent) * max(float(air_mass_kg), 0.0) / charge_gas_mass_kg, 1.0e-12)


def beck_2003_1_arrhenius_ignition_delay_s(
    *,
    c1_s: float,
    c2: float,
    reference_pressure_bar: float,
    reference_o2_percent: float,
    activation_energy_J_per_kg: float,
    activation_temperature_K: float,
    pressure_Pa: float,
    temperature_K: float,
    volume_m3: float,
    gas_mass_kg: float,
    air_mass_kg: float,
    burned_mass_kg: float,
) -> float:
    """Beck HCCI Diesel 1-Arrhenius ignition delay correlation.

    Beck formulates the pressure dependence as (p/p0)^c2 and replaces the
    lambda term with a linear oxygen-concentration term O2_air/O2_charge.
    """
    pressure_bar = max(float(pressure_Pa) * 1.0e-5, 1.0e-12)
    pressure_factor = (pressure_bar / max(float(reference_pressure_bar), 1.0e-12)) ** float(c2)
    o2_charge_percent = _hcci_charge_o2_percent(float(air_mass_kg), float(burned_mass_kg), float(reference_o2_percent))
    oxygen_factor = max(float(reference_o2_percent), 1.0e-12) / o2_charge_percent
    if float(activation_energy_J_per_kg) > 0.0:
        specific_pv_J_per_kg = max(float(pressure_Pa) * float(volume_m3) / max(float(gas_mass_kg), 1.0e-18), 1.0)
        temperature_factor = float(np.exp(float(activation_energy_J_per_kg) / specific_pv_J_per_kg))
    else:
        temperature_factor = float(np.exp(float(activation_temperature_K) / max(float(temperature_K), 1.0)))
    return max(float(c1_s) * pressure_factor * oxygen_factor * temperature_factor, 1.0e-9)


def _hcci_ignition_delay_s(
    fp,
    cyl: int,
    *,
    stage: str = 'hot',
    pressure_Pa: float,
    temp_K: float,
    volume_m3: float,
    mass_kg: float,
    air_mass_kg: float,
    burned_mass_kg: float,
    fuel_mass_kg: float,
    afr_stoich: float,
) -> float:
    ignition_models = getattr(fp, 'hcci_ignition_model_by_vol', np.zeros(0, dtype=np.int64))
    ignition_model = int(ignition_models[cyl]) if cyl < int(getattr(ignition_models, 'shape', (0,))[0]) else HCCI_IGNITION_GENERIC_LIVENGOOD_WU
    lam = lambda_from_air_and_fuel_mass(float(air_mass_kg), float(fuel_mass_kg), float(afr_stoich))
    residual_fraction = max(min(float(burned_mass_kg) / max(float(mass_kg), 1.0e-18), 1.0), 0.0)
    if ignition_model == HCCI_IGNITION_TABULATED_LIVENGOOD_WU:
        tables = getattr(fp, 'hcci_tabulated_delay_tables_by_vol', ())
        table = tables[cyl] if cyl < len(tables) else None
        tau_s = _tabulated_hcci_ignition_delay_s(
            table,
            temp_K=float(temp_K),
            pressure_Pa=float(pressure_Pa),
            lam=lam,
            residual_fraction=residual_fraction,
        )
        return tau_s
    if ignition_model in (HCCI_IGNITION_BECK_2003_1_ARRHENIUS, HCCI_IGNITION_BECK_2003_TWO_STAGE):
        if str(stage) == 'cool':
            activation_energy_J_per_kg = float(fp.hcci_cool_flame_activation_energy_by_vol_J_per_kg[cyl])
        else:
            activation_energy_J_per_kg = float(fp.hcci_hot_flame_activation_energy_by_vol_J_per_kg[cyl])
            if activation_energy_J_per_kg <= 0.0:
                activation_energy_J_per_kg = float(fp.hcci_activation_energy_by_vol_J_per_kg[cyl])
        tau_s = beck_2003_1_arrhenius_ignition_delay_s(
            c1_s=float(fp.hcci_tau_A_by_vol_s[cyl]),
            c2=float(fp.hcci_pressure_exponent_by_vol[cyl]),
            reference_pressure_bar=float(fp.hcci_reference_pressure_by_vol_bar[cyl]),
            reference_o2_percent=float(fp.hcci_reference_o2_by_vol_percent[cyl]),
            activation_energy_J_per_kg=activation_energy_J_per_kg,
            activation_temperature_K=float(fp.hcci_activation_temperature_by_vol_K[cyl]),
            pressure_Pa=float(pressure_Pa),
            temperature_K=float(temp_K),
            volume_m3=float(volume_m3),
            gas_mass_kg=float(mass_kg),
            air_mass_kg=float(air_mass_kg),
            burned_mass_kg=float(burned_mass_kg),
        )
    else:
        pressure_factor = (max(float(fp.hcci_reference_pressure_by_vol_Pa[cyl]), 1.0) / max(float(pressure_Pa), 1.0)) ** float(fp.hcci_pressure_exponent_by_vol[cyl])
        temp_factor = float(np.exp(float(fp.hcci_activation_temperature_by_vol_K[cyl]) / max(float(temp_K), 1.0)))
        lambda_factor = (max(lam, 1.0e-12) / max(float(fp.hcci_reference_lambda_by_vol[cyl]), 1.0e-12)) ** float(fp.hcci_lambda_slowdown_exponent_by_vol[cyl])
        tau_s = max(float(fp.hcci_tau_A_by_vol_s[cyl]) * pressure_factor * temp_factor * lambda_factor, 1.0e-9)
    residual_factor = 1.0 + (float(fp.hcci_residual_slowdown_factor_by_vol[cyl]) - 1.0) * residual_fraction
    return min(tau_s * residual_factor, float(fp.hcci_max_ignition_delay_by_vol_s[cyl]))


def _hcci_two_stage_enabled(fp, cyl: int) -> bool:
    enabled = getattr(fp, 'hcci_two_stage_enabled_by_vol', np.zeros(0, dtype=np.int64))
    return cyl < int(getattr(enabled, 'shape', (0,))[0]) and bool(enabled[cyl])


def _hcci_cool_flame_energy_J(fp, cyl: int, q_total_J: float) -> float:
    fraction = float(fp.hcci_cool_flame_energy_fraction_by_vol[cyl])
    return max(float(q_total_J) * min(max(fraction, 0.0), 0.95), 0.0)


def _compute_dynamic_cool_flame_legacy_linear(bundle, cyl: int, p_Pa: float, temp_K: float, air_mass_kg: float, fuel_mass_kg: float, residual_mass_kg: float, mass_kg: float, afr_stoich: float, q_total_J: float) -> tuple[float, float]:
    """Dynamische Auswertung der Cool Flame Parameter nach Beck (2003, Kap. 6)."""
    fp = bundle.free_piston
    if not getattr(fp, 'hcci_cool_flame_dynamic_enabled', True):
        return _hcci_cool_flame_energy_J(fp, cyl, q_total_J), float(fp.hcci_cool_flame_duration_by_vol_s[cyl])

    lam = lambda_from_air_and_fuel_mass(float(air_mass_kg), float(fuel_mass_kg), float(afr_stoich))
    # Beck verwendet in der Regel EGR in Prozent für die Polynome
    residual_percent = max(min(float(residual_mass_kg) / max(float(mass_kg), 1.0e-18), 1.0), 0.0) * 100.0
    
    n_rpm = 60.0 / float(bundle.cycle_period_s) if float(bundle.cycle_period_s) > 1.0e-12 else 3000.0
    n_1000 = n_rpm / 1000.0
    p_bar = float(p_Pa) * 1.0e-5

    # Koeffizienten Diesel 2 (Beck 2003, Tabelle 6.2)
    # c1(p), c2(T), c3(lam), c4(n), c5(EGR), c0
    c_dq = [0.363, 0.0, -0.333, 1.424, 0.155, 0.0075]
    # Beck (2003): Die Dauer der Cool Flame ist in Mikrosekunden (us) skaliert!
    c_dt = [-0.071, -0.0085, 0.016, -0.241, -0.645, 340.9]

    # Auswertung, falls die Kraftstoff-Koeffizienten-Arrays dynamisch geliefert werden
    dyn_dq = getattr(fp, 'hcci_cf_c_dq_by_vol', None)
    dyn_dt = getattr(fp, 'hcci_cf_c_dt_by_vol', None)
    if dyn_dq is not None and dyn_dt is not None and cyl < dyn_dq.shape[0] and np.any(dyn_dq[cyl]):
        c_dq = dyn_dq[cyl]
        c_dt = dyn_dt[cyl]

    dq_b_max = c_dq[0]*p_bar + c_dq[1]*temp_K + c_dq[2]*lam + c_dq[3]*n_1000 + c_dq[4]*residual_percent + c_dq[5]
    duration_us = c_dt[0]*p_bar + c_dt[1]*temp_K + c_dt[2]*lam + c_dt[3]*n_1000 + c_dt[4]*residual_percent + c_dt[5]
    
    dq_b_max = max(dq_b_max, 0.0)
    cool_duration_s = max(duration_us, 1.0) * 1.0e-6
    
    # Fläche des Dreiecks = 0.5 * dQ_max [J/°CA] * dt [°CA]
    # Umrechnung von Sekunden in Kurbelwinkel: °CA = t_s * 6 * n_rpm
    duration_deg = cool_duration_s * 6.0 * n_rpm
    cool_energy_J = 0.5 * dq_b_max * duration_deg

    # Konservative Obergrenze: max 15% der verfügbaren Kraftstoffenergie
    cool_energy_J = max(0.0, min(cool_energy_J, float(q_total_J) * 0.15))

    return cool_energy_J, cool_duration_s


def _gamma_pulse_energy_J(qdot_peak_W: float, peak_delay_s: float, duration_s: float, shape_m: float) -> float:
    if qdot_peak_W <= 0.0 or peak_delay_s <= 1.0e-18 or duration_s <= 1.0e-18:
        return 0.0
    samples = 96
    total = 0.0
    prev_t = 0.0
    prev_q = 0.0
    m = max(float(shape_m), 1.0e-6)
    for idx in range(1, samples + 1):
        t_i = duration_s * float(idx) / float(samples)
        x = t_i / peak_delay_s
        q_i = qdot_peak_W * (x ** m) * math.exp(m * (1.0 - x)) if x > 0.0 else 0.0
        total += 0.5 * (prev_q + q_i) * (t_i - prev_t)
        prev_t = t_i
        prev_q = q_i
    return float(total)


def _beck_vibe_cf_pulse_energy_J(qdot_peak_W: float, peak_delay_s: float, duration_s: float, shape_m: float) -> float:
    if qdot_peak_W <= 0.0 or peak_delay_s <= 1.0e-18 or duration_s <= 1.0e-18:
        return 0.0
    samples = 96
    total = 0.0
    prev_t = 0.0
    prev_q = 0.0
    m = max(float(shape_m), 1.0e-6)
    for idx in range(1, samples + 1):
        t_i = duration_s * float(idx) / float(samples)
        x = t_i / peak_delay_s
        q_i = qdot_peak_W * (x ** m) * math.exp((m / (m + 1.0)) * (1.0 - (x ** (m + 1.0)))) if x > 0.0 else 0.0
        total += 0.5 * (prev_q + q_i) * (t_i - prev_t)
        prev_t = t_i
        prev_q = q_i
    return float(total)


def _beck_empirical_cold_flame_parameters(
    bundle,
    cyl: int,
    p_Pa: float,
    temp_K: float,
    air_mass_kg: float,
    fuel_mass_kg: float,
    residual_mass_kg: float,
    mass_kg: float,
    afr_stoich: float,
    q_total_J: float,
) -> tuple[float, float, float, float]:
    fp = bundle.free_piston
    o2_ref = max(float(fp.hcci_reference_o2_by_vol_percent[cyl]), 1.0e-12)
    o2_es = _hcci_charge_o2_percent(float(air_mass_kg), float(residual_mass_kg), o2_ref)
    temp_ref_K = max(float(fp.hcci_start_temperature_min_by_vol_K[cyl]), 1.0)
    n_rpm = 60.0 / float(bundle.cycle_period_s) if float(bundle.cycle_period_s) > 1.0e-12 else 3000.0
    n_ref_rpm = 3000.0
    q_ref_J = max(float(q_total_J), 1.0e-12)
    q_fuel_J = max(float(fuel_mass_kg) * float(getattr(fp, 'combustion_lhv_J_per_kg', 0.0) or 0.0), q_ref_J)
    c_dt = fp.hcci_cf_c_dt_by_vol[cyl] if cyl < int(getattr(fp.hcci_cf_c_dt_by_vol, 'shape', (0, 0))[0]) else np.zeros(6, dtype=np.float64)
    c_dq = fp.hcci_cf_c_dq_by_vol[cyl] if cyl < int(getattr(fp.hcci_cf_c_dq_by_vol, 'shape', (0, 0))[0]) else np.zeros(6, dtype=np.float64)
    if not np.any(c_dt):
        c_dt = np.array([-0.071, -8.5e-3, 0.016, -0.241, -0.645, 340.9], dtype=np.float64)
    if not np.any(c_dq):
        c_dq = np.array([0.363, 0.0, -0.333, 1.424, 0.155, 7.5e-3], dtype=np.float64)

    def _factor(coeffs: np.ndarray, fallback_c0: float, include_o2_exp: bool) -> float:
        c1, c2, c3, c4, c5, c0 = [float(v) for v in coeffs]
        base = abs(c0) if abs(c0) > 1.0e-30 else fallback_c0
        o2_ratio = max(o2_es - 8.0, 1.0e-12) / max(o2_ref - 8.0, 1.0e-12)
        temp_ratio = max(float(temp_K), 1.0) / temp_ref_K
        fuel_ratio = q_fuel_J / q_ref_J
        speed_ratio = n_rpm / max(n_ref_rpm, 1.0e-12)
        o2_exp = math.exp(c2 * (o2_es - o2_ref)) if include_o2_exp else 1.0
        return float(base * (o2_ratio ** c1) * o2_exp * (temp_ratio ** c3) * (fuel_ratio ** c4) * (speed_ratio ** c5))

    peak_delay_s = max(_factor(c_dt, 340.9, True) * 1.0e-6, 1.0e-6)
    qdot_ref_W = q_ref_J / max(peak_delay_s, 1.0e-9)
    qdot_peak_W = max(qdot_ref_W * _factor(c_dq, 7.5e-3, False), 0.0)
    shape_m_arr = getattr(fp, 'hcci_cool_flame_shape_m_by_vol', np.zeros(0, dtype=np.float64))
    shape_m = float(shape_m_arr[cyl]) if cyl < int(getattr(shape_m_arr, 'shape', (0,))[0]) and float(shape_m_arr[cyl]) > 0.0 else 2.0
    duration_s = max(4.0 * peak_delay_s, peak_delay_s + float(fp.hcci_cool_flame_duration_by_vol_s[cyl]))
    burn_model_arr = getattr(fp, 'hcci_cool_flame_burn_model_by_vol', np.zeros(0, dtype=np.int64))
    use_beck_cf_vibe = cyl < int(getattr(burn_model_arr, 'shape', (0,))[0]) and int(burn_model_arr[cyl]) == 1
    energy_J = _beck_vibe_cf_pulse_energy_J(qdot_peak_W, peak_delay_s, duration_s, shape_m) if use_beck_cf_vibe else _gamma_pulse_energy_J(qdot_peak_W, peak_delay_s, duration_s, shape_m)
    cap_fraction = max(float(fp.hcci_cool_flame_energy_fraction_by_vol[cyl]), 0.0)
    cap_J = max(0.0, min(float(q_total_J) * cap_fraction, float(q_total_J) * 0.15))
    if cap_J > 0.0 and energy_J > cap_J:
        scale = cap_J / max(energy_J, 1.0e-18)
        qdot_peak_W *= scale
        energy_J = cap_J
    return float(energy_J), float(duration_s), float(peak_delay_s), float(qdot_peak_W)


def _compute_dynamic_cool_flame(bundle, cyl: int, p_Pa: float, temp_K: float, air_mass_kg: float, fuel_mass_kg: float, residual_mass_kg: float, mass_kg: float, afr_stoich: float, q_total_J: float) -> tuple[float, float, float, float]:
    fp = bundle.free_piston
    if not getattr(fp, 'hcci_cool_flame_dynamic_enabled', True):
        energy_J = _hcci_cool_flame_energy_J(fp, cyl, q_total_J)
        duration_s = float(fp.hcci_cool_flame_duration_by_vol_s[cyl])
        peak_delay_s = max(0.25 * duration_s, 1.0e-6)
        qdot_peak_W = energy_J / max(peak_delay_s, 1.0e-9)
        return float(energy_J), float(duration_s), float(peak_delay_s), float(qdot_peak_W)
    return _beck_empirical_cold_flame_parameters(bundle, cyl, p_Pa, temp_K, air_mass_kg, fuel_mass_kg, residual_mass_kg, mass_kg, afr_stoich, q_total_J)

def _fueling_mode_for_cylinder(bundle, cylinder_idx: int) -> int:
    fp = getattr(bundle, 'free_piston', None)
    if fp is None:
        return FUELING_FIXED
    by_vol = getattr(fp, 'combustion_fueling_mode_by_vol', np.zeros(0, dtype=np.int64))
    cyl = int(cylinder_idx)
    if cyl >= 0 and cyl < int(getattr(by_vol, 'shape', (0,))[0]):
        return int(by_vol[cyl])
    mode = str(getattr(fp, 'combustion_fueling_mode', 'fixed_energy'))
    if mode == 'lambda_from_cylinder_mass_at_slot_close':
        return FUELING_SLOT_CLOSE
    if mode == 'lambda_from_cylinder_air_at_slot_close_vapor_injector':
        return FUELING_VAPOR_INJECTOR
    return FUELING_FIXED


def _cylinder_uses_slot_closure_lambda(bundle, cylinder_idx: int) -> bool:
    return _fueling_mode_for_cylinder(bundle, int(cylinder_idx)) == FUELING_SLOT_CLOSE


def _cylinder_uses_vapor_injector(bundle, cylinder_idx: int) -> bool:
    return _fueling_mode_for_cylinder(bundle, int(cylinder_idx)) == FUELING_VAPOR_INJECTOR


def _slot_open_threshold_m2(fp, cylinder_idx: int) -> float:
    by_vol = getattr(fp, 'combustion_slot_open_threshold_by_vol_m2', np.zeros(0, dtype=np.float64))
    cyl = int(cylinder_idx)
    if cyl < int(getattr(by_vol, 'shape', (0,))[0]) and float(by_vol[cyl]) >= 0.0:
        return float(by_vol[cyl])
    return float(getattr(fp, 'combustion_slot_open_threshold_m2', 1.0e-7) or 1.0e-7)


def _slot_closed_threshold_m2(fp, cylinder_idx: int) -> float:
    by_vol = getattr(fp, 'combustion_slot_closed_threshold_by_vol_m2', np.zeros(0, dtype=np.float64))
    cyl = int(cylinder_idx)
    if cyl < int(getattr(by_vol, 'shape', (0,))[0]) and float(by_vol[cyl]) >= 0.0:
        return float(by_vol[cyl])
    return float(getattr(fp, 'combustion_slot_closed_threshold_m2', 1.0e-9) or 1.0e-9)


def _compression_velocity_threshold_m_per_s(fp, cylinder_idx: int) -> float:
    by_vol = getattr(fp, 'combustion_compression_velocity_threshold_by_vol_m_per_s', np.zeros(0, dtype=np.float64))
    cyl = int(cylinder_idx)
    if cyl < int(getattr(by_vol, 'shape', (0,))[0]) and float(by_vol[cyl]) >= 0.0:
        return float(by_vol[cyl])
    return float(getattr(fp, 'combustion_compression_velocity_threshold_m_per_s', 0.02) or 0.02)


def free_piston_combustion_enabled(bundle) -> bool:
    feature_flags = getattr(bundle, 'feature_flags', None)
    return bool(feature_flags is not None and feature_flags.size > F_COMB and int(feature_flags[F_COMB]) == 1)


def free_piston_uses_slot_closure_lambda(bundle) -> bool:
    if not free_piston_combustion_enabled(bundle):
        return False
    fp = getattr(bundle, 'free_piston', None)
    if fp is None:
        return False
    return any(_cylinder_uses_slot_closure_lambda(bundle, int(cyl)) and _comb_idx_for_cylinder(bundle, int(cyl)) >= 0 for cyl in getattr(bundle, 'cylinder_indices', []))


def free_piston_uses_vapor_injector(bundle) -> bool:
    if not free_piston_combustion_enabled(bundle):
        return False
    fp = getattr(bundle, 'free_piston', None)
    if fp is None:
        return False
    return any(_cylinder_uses_vapor_injector(bundle, int(cyl)) and _comb_idx_for_cylinder(bundle, int(cyl)) >= 0 for cyl in getattr(bundle, 'cylinder_indices', []))


def free_piston_cylinder_uses_latched_fuel(bundle, cylinder_idx: int) -> bool:
    if not free_piston_combustion_enabled(bundle):
        return False
    cyl = int(cylinder_idx)
    if _comb_idx_for_cylinder(bundle, cyl) < 0:
        return False
    return _cylinder_uses_slot_closure_lambda(bundle, cyl) or _cylinder_uses_vapor_injector(bundle, cyl)


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
        'runtime_cool_flame_active_by_vol',
        'runtime_cool_flame_done_by_vol',
        'runtime_injector_active_by_vol',
        'runtime_slotclose_charge_active_by_vol',
        'runtime_cf_active_by_vol',
        'runtime_hf_active_by_vol',
    )
    float_names = (
        'runtime_latched_cylinder_mass_by_vol_kg',
        'runtime_latched_fuel_mass_by_vol_kg',
        'runtime_latched_energy_by_vol_J',
        'runtime_last_slot_area_by_vol_m2',
        'runtime_soc_time_by_vol_s',
        'runtime_soc_end_time_by_vol_s',
        'runtime_soc_energy_by_vol_J',
        'runtime_injector_time_by_vol_s',
        'runtime_injector_end_time_by_vol_s',
        'runtime_injector_target_fuel_by_vol_kg',
        'runtime_injector_injected_by_vol_kg',
        'runtime_injector_rate_by_vol_kg_per_s',
        'runtime_slotclose_charge_time_by_vol_s',
        'runtime_slotclose_charge_end_time_by_vol_s',
        'runtime_slotclose_charge_rate_by_vol_kg_per_s',
        'runtime_slotclose_charge_target_fuel_by_vol_kg',
        'runtime_hcci_integral_by_vol',
        'runtime_hcci_cool_integral_by_vol',
        'runtime_hcci_last_update_time_by_vol_s',
        'runtime_hcci_tau_by_vol_s',
        'runtime_hcci_cool_tau_by_vol_s',
        'runtime_cool_flame_time_by_vol_s',
        'runtime_cool_flame_end_time_by_vol_s',
        'runtime_cool_flame_energy_by_vol_J',
        'runtime_cool_flame_peak_delay_by_vol_s',
        'runtime_cool_flame_qdot_peak_by_vol_W',
        'runtime_cool_flame_duration_model_by_vol_s',
        'runtime_cf_integral_by_vol',
        'runtime_cf_tau_by_vol_s',
        'runtime_hf_integral_by_vol',
        'runtime_hf_tau_by_vol_s',
    )

    if not hasattr(type(fp), '_dynamic_arrays'):
        setattr(type(fp), '_dynamic_arrays', {})
    fp_id = id(fp)
    if fp_id not in type(fp)._dynamic_arrays:
        type(fp)._dynamic_arrays[fp_id] = {}

    # Work around objects that implement __slots__ and therefore cannot always
    # receive new instance attributes. We instead attach runtime arrays via a
    # per-instance registry on the type, exposed through dynamically created
    # properties.
    for name in int_names:
        arr = getattr(fp, name, None)
        if arr is None or int(getattr(arr, 'shape', (0,))[0]) != n_vol:
            try:
                setattr(fp, name, np.zeros(n_vol, dtype=np.int64))
            except AttributeError:
                type(fp)._dynamic_arrays[fp_id][name] = np.zeros(n_vol, dtype=np.int64)
                if not hasattr(type(fp), name):
                    setattr(type(fp), name, property(lambda self, n=name: type(self)._dynamic_arrays.get(id(self), {}).get(n)))
    for name in float_names:
        arr = getattr(fp, name, None)
        if arr is None or int(getattr(arr, 'shape', (0,))[0]) != n_vol:
            try:
                setattr(fp, name, np.zeros(n_vol, dtype=np.float64))
            except AttributeError:
                type(fp)._dynamic_arrays[fp_id][name] = np.zeros(n_vol, dtype=np.float64)
                if not hasattr(type(fp), name):
                    setattr(type(fp), name, property(lambda self, n=name: type(self)._dynamic_arrays.get(id(self), {}).get(n)))


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
    return free_piston_equivalent_linear_kinematics(
        q_m,
        q_v_m_per_s,
        sign,
        kinematics_type=str(getattr(fp, 'kinematics_type', 'linear') or 'linear'),
        x_min_m=float(fp.x_min_m),
        x_max_m=float(fp.x_max_m),
        angle_min_rad=float(getattr(fp, 'rotary_angle_min_rad', 0.0) or 0.0),
        angle_max_rad=float(getattr(fp, 'rotary_angle_max_rad', 0.0) or 0.0),
        effective_radius_m=float(getattr(fp, 'rotary_effective_radius_m', 1.0) or 1.0),
    )


def _arm_vapor_injector(fp, t_s: float, fuel_mass_kg: float, cylinder_idx: int | None = None) -> None:
    duration_s = float(getattr(fp, 'injector_duration_s', 0.0) or 0.0)
    if cylinder_idx is not None:
        by_vol = getattr(fp, 'injector_duration_by_vol_s', np.zeros(0, dtype=np.float64))
        cyl = int(cylinder_idx)
        if cyl < int(getattr(by_vol, 'shape', (0,))[0]) and float(by_vol[cyl]) > 0.0:
            duration_s = float(by_vol[cyl])
    if duration_s <= 0.0 or fuel_mass_kg <= 0.0:
        fp.runtime_injector_active = False
        fp.runtime_injector_time_s = float(t_s)
        fp.runtime_injector_end_time_s = float(t_s)
        fp.runtime_injector_target_fuel_mass_kg = 0.0
        fp.runtime_injector_injected_mass_kg = 0.0
        fp.runtime_injector_rate_kg_per_s = 0.0
        if int(getattr(getattr(fp, 'runtime_injector_active_by_vol', np.zeros(0)), 'shape', (0,))[0]) >= int(bundle.vol_matrix.shape[0]):
            fp.runtime_injector_active_by_vol.fill(0)
            fp.runtime_injector_time_by_vol_s.fill(0.0)
            fp.runtime_injector_end_time_by_vol_s.fill(0.0)
            fp.runtime_injector_target_fuel_by_vol_kg.fill(0.0)
            fp.runtime_injector_injected_by_vol_kg.fill(0.0)
            fp.runtime_injector_rate_by_vol_kg_per_s.fill(0.0)
        if cylinder_idx is not None and int(getattr(getattr(fp, 'runtime_injector_active_by_vol', np.zeros(0)), 'shape', (0,))[0]) > int(cylinder_idx):
            cyl = int(cylinder_idx)
            fp.runtime_injector_active_by_vol[cyl] = 0
            fp.runtime_injector_time_by_vol_s[cyl] = float(t_s)
            fp.runtime_injector_end_time_by_vol_s[cyl] = float(t_s)
            fp.runtime_injector_target_fuel_by_vol_kg[cyl] = 0.0
            fp.runtime_injector_injected_by_vol_kg[cyl] = 0.0
            fp.runtime_injector_rate_by_vol_kg_per_s[cyl] = 0.0
        return
    fp.runtime_injector_active = True
    fp.runtime_injector_time_s = float(t_s)
    fp.runtime_injector_end_time_s = float(t_s + duration_s)
    fp.runtime_injector_target_fuel_mass_kg = float(fuel_mass_kg)
    fp.runtime_injector_injected_mass_kg = 0.0
    fp.runtime_injector_rate_kg_per_s = float(fuel_mass_kg / duration_s)
    if cylinder_idx is not None and int(getattr(getattr(fp, 'runtime_injector_active_by_vol', np.zeros(0)), 'shape', (0,))[0]) > int(cylinder_idx):
        cyl = int(cylinder_idx)
        fp.runtime_injector_active_by_vol[cyl] = 1
        fp.runtime_injector_time_by_vol_s[cyl] = float(t_s)
        fp.runtime_injector_end_time_by_vol_s[cyl] = float(t_s + duration_s)
        fp.runtime_injector_target_fuel_by_vol_kg[cyl] = float(fuel_mass_kg)
        fp.runtime_injector_injected_by_vol_kg[cyl] = 0.0
        fp.runtime_injector_rate_by_vol_kg_per_s[cyl] = float(fuel_mass_kg / duration_s)


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
    if cylinder_idx is not None:
        idx = int(cylinder_idx)
        if free_piston_cylinder_uses_latched_fuel(bundle, idx):
            _ensure_runtime_arrays(bundle)
            return float(fp.runtime_latched_energy_by_vol_J[idx]) if bool(fp.runtime_latch_valid_by_vol[idx]) else 0.0
    elif free_piston_uses_slot_closure_lambda(bundle) or free_piston_uses_vapor_injector(bundle):
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
            fp.runtime_hcci_cool_integral_by_vol[cyl] = 0.0
            fp.runtime_cool_flame_active_by_vol[cyl] = 0
            fp.runtime_cool_flame_done_by_vol[cyl] = 0
            continue

        q_total_J = _current_combustion_energy_J(bundle, cyl)
        if q_total_J <= 0.0 or bool(fp.runtime_soc_active_by_vol[cyl]):
            continue

        mass = float(bundle.state_layout.gas_mass_from_state(y_state, cyl))
        energy = float(y_state[int(bundle.state_layout.energy_index(cyl))])
        air_mass = float(bundle.state_layout.air_mass_from_state(y_state, cyl))
        burned_mass = float(bundle.state_layout.burned_mass_from_state(y_state, cyl))
        residual_mass = burned_mass
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
        tau_s = _hcci_ignition_delay_s(
            fp,
            cyl,
            pressure_Pa=pressure_Pa,
            temp_K=temp_K,
            volume_m3=volume,
            mass_kg=mass,
            air_mass_kg=air_mass,
            burned_mass_kg=residual_mass,
            fuel_mass_kg=fuel_mass,
            afr_stoich=afr,
        )
        fp.runtime_hcci_tau_by_vol_s[cyl] = tau_s
        if _hcci_two_stage_enabled(fp, cyl) and not bool(fp.runtime_cool_flame_done_by_vol[cyl]):
            tau_s = _hcci_ignition_delay_s(
                fp,
                cyl,
                stage='cool',
                pressure_Pa=pressure_Pa,
                temp_K=temp_K,
                volume_m3=volume,
                mass_kg=mass,
                air_mass_kg=air_mass,
                burned_mass_kg=residual_mass,
                fuel_mass_kg=fuel_mass,
                afr_stoich=afr,
            )
            fp.runtime_hcci_cool_tau_by_vol_s[cyl] = tau_s
            fp.runtime_hcci_cool_integral_by_vol[cyl] += dt_s / max(tau_s, 1.0e-12)
            if fp.runtime_hcci_cool_integral_by_vol[cyl] >= 1.0:
                cool_energy_J, cool_duration_s, cool_peak_delay_s, cool_qdot_peak_W = _compute_dynamic_cool_flame(
                    bundle, cyl, pressure_Pa, temp_K, air_mass, fuel_mass, residual_mass, mass, afr, q_total_J
                )
                if cool_energy_J > 0.0 and cool_duration_s > 0.0:
                    fp.runtime_cool_flame_active_by_vol[cyl] = 1
                    fp.runtime_cool_flame_done_by_vol[cyl] = 1
                    fp.runtime_cool_flame_time_by_vol_s[cyl] = float(t_s)
                    fp.runtime_cool_flame_end_time_by_vol_s[cyl] = float(t_s + cool_duration_s)
                    fp.runtime_cool_flame_energy_by_vol_J[cyl] = float(cool_energy_J)
                    fp.runtime_cool_flame_peak_delay_by_vol_s[cyl] = float(cool_peak_delay_s)
                    fp.runtime_cool_flame_qdot_peak_by_vol_W[cyl] = float(cool_qdot_peak_W)
                    fp.runtime_cool_flame_duration_model_by_vol_s[cyl] = float(cool_duration_s)
                else:
                    fp.runtime_cool_flame_done_by_vol[cyl] = 1
                fp.runtime_hcci_cool_integral_by_vol[cyl] = 0.0
            continue
        if bool(fp.runtime_cool_flame_active_by_vol[cyl]) and float(t_s) >= float(fp.runtime_cool_flame_end_time_by_vol_s[cyl]) - 1.0e-15:
            fp.runtime_cool_flame_active_by_vol[cyl] = 0
        fp.runtime_hcci_integral_by_vol[cyl] += dt_s / max(tau_s, 1.0e-12)
        if fp.runtime_hcci_integral_by_vol[cyl] >= 1.0:
            duration_s = _time_mode_duration_s(bundle, cyl)
            if duration_s > 0.0:
                fp.runtime_soc_active_by_vol[cyl] = 1
                fp.runtime_soc_time_by_vol_s[cyl] = float(t_s)
                fp.runtime_soc_end_time_by_vol_s[cyl] = float(t_s + duration_s)
                if _hcci_two_stage_enabled(fp, cyl):
                    cf_energy = float(fp.runtime_cool_flame_energy_by_vol_J[cyl])
                    fp.runtime_soc_energy_by_vol_J[cyl] = max(0.0, float(q_total_J - cf_energy))
                else:
                    fp.runtime_soc_energy_by_vol_J[cyl] = float(q_total_J)
                fp.runtime_hcci_integral_by_vol[cyl] = 0.0
                if cyl == int(bundle.cylinder_indices[0]):
                    fp.runtime_soc_active = True
                    fp.runtime_soc_time_s = float(t_s)
                    fp.runtime_soc_end_time_s = float(t_s + duration_s)
                    fp.runtime_soc_energy_J = float(fp.runtime_soc_energy_by_vol_J[cyl])


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
        fp = bundle.free_piston
        cv_default = float(bundle.gas_props[1])
        use_promo_thermo = bundle.gas_props.shape[0] > 4 and float(bundle.gas_props[4]) >= 0.5
        hcci_integral = 0.0
        hcci_cool_integral = 0.0
        cool_done = False
        cool_energy_latched_J = 0.0
        active = False
        soc_time_s = 0.0
        soc_end_time_s = 0.0
        soc_energy_J = 0.0
        last_t = float(t[0]) if n > 0 else 0.0
        for k in range(n):
            t_k = float(t[k])
            dt_s = max(0.0, t_k - last_t)
            last_t = t_k
            if active and t_k >= soc_end_time_s - 1.0e-15:
                active = False

            if active:
                soc_time_hist[k] = soc_time_s
                soc_energy_hist[k] = soc_energy_J
                active_hist[k] = 1.0
                continue

            x_m, v_m_per_s = _local_piston_kinematics_for_volume(bundle, y[:, k], cyl_idx)
            if not free_piston_is_compression_stroke(v_m_per_s, x_m, fp.x_min_m, fp.x_max_m):
                hcci_integral = 0.0
                hcci_cool_integral = 0.0
                cool_done = False
                continue

            if latched_energy_hist is not None:
                q_total_J = float(latched_energy_hist[k])
            else:
                q_total_J = float(comb_row[int(CombCol.FUEL_MASS_PER_CYCLE)] * comb_row[int(CombCol.LHV)])
            if q_total_J <= 0.0:
                continue

            mass = float(bundle.state_layout.gas_mass_from_state(y[:, k], cyl_idx))
            energy = float(y[int(bundle.state_layout.energy_index(cyl_idx)), k])
            air_mass = float(bundle.state_layout.air_mass_from_state(y[:, k], cyl_idx))
            burned_mass = float(bundle.state_layout.burned_mass_from_state(y[:, k], cyl_idx))
            residual_mass = burned_mass
            lhv = float(bundle.combustion_lhv_by_vol[cyl_idx]) if getattr(bundle, 'combustion_lhv_by_vol', None) is not None and cyl_idx < int(bundle.combustion_lhv_by_vol.shape[0]) else float(getattr(fp, 'combustion_lhv_J_per_kg', 0.0) or 0.0)
            comb_eff = float(bundle.combustion_efficiency_by_vol[cyl_idx]) if getattr(bundle, 'combustion_efficiency_by_vol', None) is not None and cyl_idx < int(bundle.combustion_efficiency_by_vol.shape[0]) else float(getattr(fp, 'combustion_efficiency_0to1', 1.0) or 1.0)
            fuel_mass = q_total_J / max(lhv * comb_eff, 1.0e-18)
            if mass <= 1.0e-18 or air_mass <= 1.0e-18 or fuel_mass <= 1.0e-18:
                continue

            volume = cylinder_volume_from_position(fp.clearance_volume_m3, fp.piston_area_m2, x_m, fp.x_min_m, fp.x_max_m)
            if use_promo_thermo:
                fuel_vapor_mass = float(bundle.state_layout.fuel_vapor_mass_from_state(y[:, k], cyl_idx))
                temp_K, _cp, cv_i, gas_constant_i, _kappa = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, cv_default)
                pressure_Pa = pressure_from_state(mass, energy, volume, gas_constant_i, cv_i)
            else:
                temp_K = max(energy / max(mass * cv_default, 1.0e-18), 1.0)
                pressure_Pa = pressure_from_state(mass, energy, volume, float(bundle.gas_props[2]), cv_default)

            if temp_K < float(fp.hcci_start_temperature_min_by_vol_K[cyl_idx]) or pressure_Pa < float(fp.hcci_start_pressure_min_by_vol_Pa[cyl_idx]):
                continue

            afr = float(bundle.combustion_afr_stoich_by_vol[cyl_idx]) if getattr(bundle, 'combustion_afr_stoich_by_vol', None) is not None and cyl_idx < int(bundle.combustion_afr_stoich_by_vol.shape[0]) else float(getattr(fp, 'combustion_afr_stoich_kg_air_per_kg_fuel', 14.5) or 14.5)
            tau_s = _hcci_ignition_delay_s(
                fp,
                cyl_idx,
                pressure_Pa=pressure_Pa,
                temp_K=temp_K,
                volume_m3=volume,
                mass_kg=mass,
                air_mass_kg=air_mass,
                burned_mass_kg=residual_mass,
                fuel_mass_kg=fuel_mass,
                afr_stoich=afr,
            )
            if _hcci_two_stage_enabled(fp, cyl_idx) and not cool_done:
                tau_s = _hcci_ignition_delay_s(
                    fp,
                    cyl_idx,
                    stage='cool',
                    pressure_Pa=pressure_Pa,
                    temp_K=temp_K,
                    volume_m3=volume,
                    mass_kg=mass,
                    air_mass_kg=air_mass,
                    burned_mass_kg=residual_mass,
                    fuel_mass_kg=fuel_mass,
                    afr_stoich=afr,
                )
                hcci_cool_integral += dt_s / max(tau_s, 1.0e-12)
                if hcci_cool_integral >= 1.0:
                    cool_done = True
                    hcci_cool_integral = 0.0
                    cool_energy_latched_J, _cool_duration_s, _cool_peak_delay_s, _cool_qdot_peak_W = _compute_dynamic_cool_flame(
                        bundle, cyl_idx, pressure_Pa, temp_K, air_mass, fuel_mass, residual_mass, mass, afr, q_total_J
                    )
                continue
            hcci_integral += dt_s / max(tau_s, 1.0e-12)
            if hcci_integral >= 1.0:
                duration_s = _time_mode_duration_s(bundle, cyl_idx)
                if duration_s > 0.0:
                    active = True
                    soc_time_s = t_k
                    soc_end_time_s = t_k + duration_s
                    if _hcci_two_stage_enabled(fp, cyl_idx):
                        soc_energy_J = max(0.0, q_total_J - cool_energy_latched_J)
                    else:
                        soc_energy_J = q_total_J
                    hcci_integral = 0.0
                    soc_time_hist[k] = soc_time_s
                    soc_energy_hist[k] = soc_energy_J
                    active_hist[k] = 1.0
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


def replay_free_piston_cool_flame_series(bundle, t: np.ndarray, y: np.ndarray, latched_energy_hist: np.ndarray | None = None, cylinder_idx: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = int(t.shape[0]) if t.ndim == 1 else 0
    cf_time_hist = np.zeros(n, dtype=np.float64)
    cf_energy_hist = np.zeros(n, dtype=np.float64)
    cf_active_hist = np.zeros(n, dtype=np.float64)
    cf_duration_hist = np.zeros(n, dtype=np.float64)
    cf_peak_delay_hist = np.zeros(n, dtype=np.float64)
    cf_qdot_peak_hist = np.zeros(n, dtype=np.float64)
    if not free_piston_uses_time_vibe(bundle):
        return cf_time_hist, cf_energy_hist, cf_active_hist, cf_duration_hist, cf_peak_delay_hist, cf_qdot_peak_hist

    fp = bundle.free_piston
    cyl_idx = int(cylinder_idx) if cylinder_idx is not None else int(bundle.cylinder_indices[0])
    comb_row = _comb_row_for_cylinder(bundle, cyl_idx)
    if comb_row is None or _comb_start_mode(bundle, cyl_idx) != int(CombStartMode.AUTOIGNITION) or not _hcci_two_stage_enabled(fp, cyl_idx):
        return cf_time_hist, cf_energy_hist, cf_active_hist, cf_duration_hist, cf_peak_delay_hist, cf_qdot_peak_hist

    cv_default = float(bundle.gas_props[1])
    use_promo_thermo = bundle.gas_props.shape[0] > 4 and float(bundle.gas_props[4]) >= 0.5
    cool_integral = 0.0
    cool_done = False
    active = False
    cf_time_s = 0.0
    cf_end_s = 0.0
    cf_energy_J = 0.0
    cf_duration_s = 0.0
    cf_peak_delay_s = 0.0
    cf_qdot_peak_W = 0.0
    last_t = float(t[0]) if n > 0 else 0.0
    for k in range(n):
        t_k = float(t[k])
        dt_s = max(0.0, t_k - last_t)
        last_t = t_k
        if active and t_k >= cf_end_s - 1.0e-15:
            active = False
        if active:
            cf_time_hist[k] = cf_time_s
            cf_energy_hist[k] = cf_energy_J
            cf_active_hist[k] = 1.0
            cf_duration_hist[k] = cf_duration_s
            cf_peak_delay_hist[k] = cf_peak_delay_s
            cf_qdot_peak_hist[k] = cf_qdot_peak_W
            continue

        x_m, v_m_per_s = _local_piston_kinematics_for_volume(bundle, y[:, k], cyl_idx)
        if not free_piston_is_compression_stroke(v_m_per_s, x_m, fp.x_min_m, fp.x_max_m):
            cool_integral = 0.0
            cool_done = False
            continue
        q_total_J = float(latched_energy_hist[k]) if latched_energy_hist is not None else float(comb_row[int(CombCol.FUEL_MASS_PER_CYCLE)] * comb_row[int(CombCol.LHV)])
        if q_total_J <= 0.0 or cool_done:
            continue
        mass = float(bundle.state_layout.gas_mass_from_state(y[:, k], cyl_idx))
        energy = float(y[int(bundle.state_layout.energy_index(cyl_idx)), k])
        air_mass = float(bundle.state_layout.air_mass_from_state(y[:, k], cyl_idx))
        burned_mass = float(bundle.state_layout.burned_mass_from_state(y[:, k], cyl_idx))
        lhv = float(bundle.combustion_lhv_by_vol[cyl_idx]) if getattr(bundle, 'combustion_lhv_by_vol', None) is not None and cyl_idx < int(bundle.combustion_lhv_by_vol.shape[0]) else float(getattr(fp, 'combustion_lhv_J_per_kg', 0.0) or 0.0)
        comb_eff = float(bundle.combustion_efficiency_by_vol[cyl_idx]) if getattr(bundle, 'combustion_efficiency_by_vol', None) is not None and cyl_idx < int(bundle.combustion_efficiency_by_vol.shape[0]) else float(getattr(fp, 'combustion_efficiency_0to1', 1.0) or 1.0)
        fuel_mass = q_total_J / max(lhv * comb_eff, 1.0e-18)
        if mass <= 1.0e-18 or air_mass <= 1.0e-18 or fuel_mass <= 1.0e-18:
            continue
        volume = cylinder_volume_from_position(fp.clearance_volume_m3, fp.piston_area_m2, x_m, fp.x_min_m, fp.x_max_m)
        if use_promo_thermo:
            fuel_vapor_mass = float(bundle.state_layout.fuel_vapor_mass_from_state(y[:, k], cyl_idx))
            temp_K, _cp, cv_i, gas_constant_i, _kappa = properties_from_mass_energy_components_quellen(mass, energy, air_mass, fuel_vapor_mass, burned_mass, cv_default)
            pressure_Pa = pressure_from_state(mass, energy, volume, gas_constant_i, cv_i)
        else:
            temp_K = max(energy / max(mass * cv_default, 1.0e-18), 1.0)
            pressure_Pa = pressure_from_state(mass, energy, volume, float(bundle.gas_props[2]), cv_default)
        if temp_K < float(fp.hcci_start_temperature_min_by_vol_K[cyl_idx]) or pressure_Pa < float(fp.hcci_start_pressure_min_by_vol_Pa[cyl_idx]):
            continue
        afr = float(bundle.combustion_afr_stoich_by_vol[cyl_idx]) if getattr(bundle, 'combustion_afr_stoich_by_vol', None) is not None and cyl_idx < int(bundle.combustion_afr_stoich_by_vol.shape[0]) else float(getattr(fp, 'combustion_afr_stoich_kg_air_per_kg_fuel', 14.5) or 14.5)
        tau_s = _hcci_ignition_delay_s(
            fp,
            cyl_idx,
            stage='cool',
            pressure_Pa=pressure_Pa,
            temp_K=temp_K,
            volume_m3=volume,
            mass_kg=mass,
            air_mass_kg=air_mass,
            burned_mass_kg=burned_mass,
            fuel_mass_kg=fuel_mass,
            afr_stoich=afr,
        )
        cool_integral += dt_s / max(tau_s, 1.0e-12)
        if cool_integral >= 1.0:
            cf_energy_J, cf_duration_s, cf_peak_delay_s, cf_qdot_peak_W = _compute_dynamic_cool_flame(
                bundle, cyl_idx, pressure_Pa, temp_K, air_mass, fuel_mass, burned_mass, mass, afr, q_total_J
            )
            cool_integral = 0.0
            cool_done = True
            if cf_energy_J > 0.0 and cf_duration_s > 0.0:
                active = True
                cf_time_s = t_k
                cf_end_s = t_k + cf_duration_s
                cf_time_hist[k] = cf_time_s
                cf_energy_hist[k] = cf_energy_J
                cf_active_hist[k] = 1.0
                cf_duration_hist[k] = cf_duration_s
                cf_peak_delay_hist[k] = cf_peak_delay_s
                cf_qdot_peak_hist[k] = cf_qdot_peak_W
    return cf_time_hist, cf_energy_hist, cf_active_hist, cf_duration_hist, cf_peak_delay_hist, cf_qdot_peak_hist


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


def compute_lambda_energy_from_cylinder_mass(cylinder_unburned_mass_kg: float, bundle, cylinder_idx: int | None = None) -> tuple[float, float]:
    fp = bundle.free_piston
    if fp is None:
        return 0.0, 0.0
    m_air_ref_kg = max(float(cylinder_unburned_mass_kg), 0.0)
    cyl = int(cylinder_idx) if cylinder_idx is not None else -1
    lambda_target = float(getattr(fp, 'combustion_lambda_target', 0.0) or 0.0)
    afr_stoich = float(getattr(fp, 'combustion_afr_stoich_kg_air_per_kg_fuel', 14.5) or 14.5)
    combustion_efficiency = float(getattr(fp, 'combustion_efficiency_0to1', 1.0) or 1.0)
    lhv = float(getattr(fp, 'combustion_lhv_J_per_kg', 0.0) or 0.0)
    if cyl >= 0:
        if getattr(bundle, 'combustion_afr_stoich_by_vol', None) is not None and cyl < int(bundle.combustion_afr_stoich_by_vol.shape[0]):
            afr_stoich = float(bundle.combustion_afr_stoich_by_vol[cyl])
        if getattr(bundle, 'combustion_lambda_target_by_vol', None) is not None and cyl < int(bundle.combustion_lambda_target_by_vol.shape[0]) and float(bundle.combustion_lambda_target_by_vol[cyl]) > 0.0:
            lambda_target = float(bundle.combustion_lambda_target_by_vol[cyl])
        if getattr(bundle, 'combustion_efficiency_by_vol', None) is not None and cyl < int(bundle.combustion_efficiency_by_vol.shape[0]):
            combustion_efficiency = float(bundle.combustion_efficiency_by_vol[cyl])
        if getattr(bundle, 'combustion_lhv_by_vol', None) is not None and cyl < int(bundle.combustion_lhv_by_vol.shape[0]):
            lhv = float(bundle.combustion_lhv_by_vol[cyl])
    denom = max(lambda_target * afr_stoich, 1.0e-18)
    fuel_mass_kg = m_air_ref_kg / denom
    energy_J = combustion_efficiency * fuel_mass_kg * lhv
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
        if not free_piston_cylinder_uses_latched_fuel(bundle, cyl):
            continue
        x_m, v_m_per_s = _local_piston_kinematics_for_volume(bundle, y0, cyl)
        area_sum_m2 = _cylinder_slot_area_sum_m2(bundle, x_m, cyl)
        fp.runtime_last_slot_area_by_vol_m2[cyl] = float(area_sum_m2)
        if cyl == int(bundle.cylinder_indices[0]):
            fp.runtime_last_slot_area_sum_m2 = float(area_sum_m2)
        if area_sum_m2 > _slot_open_threshold_m2(fp, cyl):
            fp.runtime_slots_were_open_by_vol[cyl] = 1
            fp.runtime_latch_valid_by_vol[cyl] = 0
            if cyl < int(getattr(fp.runtime_hcci_integral_by_vol, 'shape', (0,))[0]):
                fp.runtime_hcci_integral_by_vol[cyl] = 0.0
                fp.runtime_hcci_cool_integral_by_vol[cyl] = 0.0
                fp.runtime_cool_flame_active_by_vol[cyl] = 0
                fp.runtime_cool_flame_done_by_vol[cyl] = 0
            if cyl == int(bundle.cylinder_indices[0]):
                fp.runtime_slots_were_open = True
                fp.runtime_latch_valid = False
            continue
        if not (v_m_per_s < -_compression_velocity_threshold_m_per_s(fp, cyl) and area_sum_m2 <= _slot_closed_threshold_m2(fp, cyl)):
            continue
        air_idx = int(bundle.state_layout.air_mass_index(cyl))
        cylinder_air_mass_kg = float(y0[air_idx])
        fuel_mass_kg, energy_J = compute_lambda_energy_from_cylinder_mass(cylinder_air_mass_kg, bundle, cyl)
        fp.runtime_latched_cylinder_mass_by_vol_kg[cyl] = cylinder_air_mass_kg
        fp.runtime_latched_fuel_mass_by_vol_kg[cyl] = fuel_mass_kg
        fp.runtime_latched_energy_by_vol_J[cyl] = energy_J
        fp.runtime_latch_valid_by_vol[cyl] = 1
        fp.runtime_slots_were_open_by_vol[cyl] = 0
        if cyl < int(getattr(fp.runtime_hcci_integral_by_vol, 'shape', (0,))[0]):
            fp.runtime_hcci_integral_by_vol[cyl] = 0.0
            fp.runtime_hcci_cool_integral_by_vol[cyl] = 0.0
            fp.runtime_cool_flame_active_by_vol[cyl] = 0
            fp.runtime_cool_flame_done_by_vol[cyl] = 0
        if cyl == int(bundle.cylinder_indices[0]):
            fp.runtime_latched_cylinder_mass_kg = cylinder_air_mass_kg
            fp.runtime_latched_fuel_mass_kg = fuel_mass_kg
            fp.runtime_latched_energy_J = energy_J
            fp.runtime_latch_valid = True
            fp.runtime_slots_were_open = False
        if _cylinder_uses_slot_closure_lambda(bundle, cyl):
            duration_s = float(getattr(bundle.simulation, 'dt_s', 0.0))
            _arm_slotclose_charge(fp, 0.0, fuel_mass_kg, duration_s)
            fp.runtime_slotclose_charge_active_by_vol[cyl] = 1 if fuel_mass_kg > 0.0 and duration_s > 0.0 else 0
            fp.runtime_slotclose_charge_time_by_vol_s[cyl] = 0.0
            fp.runtime_slotclose_charge_end_time_by_vol_s[cyl] = duration_s
            fp.runtime_slotclose_charge_target_fuel_by_vol_kg[cyl] = fuel_mass_kg
            fp.runtime_slotclose_charge_rate_by_vol_kg_per_s[cyl] = fuel_mass_kg / duration_s if duration_s > 0.0 else 0.0
        if _cylinder_uses_vapor_injector(bundle, cyl):
            _arm_vapor_injector(fp, 0.0, fuel_mass_kg, cyl)


def update_free_piston_combustion_latch_state(bundle, t_s: float, y_state: np.ndarray) -> None:
    _update_time_combustion_state(bundle, t_s, y_state)
    fp = bundle.free_piston
    _ensure_runtime_arrays(bundle)
    if fp is not None:
        _update_vapor_injector_state(fp, t_s)
        _update_slotclose_charge_state(fp, t_s)
        for cyl_idx in getattr(bundle, 'cylinder_indices', []):
            cyl = int(cyl_idx)
            if bool(fp.runtime_injector_active_by_vol[cyl]) and float(t_s) >= float(fp.runtime_injector_end_time_by_vol_s[cyl]) - 1.0e-15:
                fp.runtime_injector_active_by_vol[cyl] = 0
            if bool(fp.runtime_slotclose_charge_active_by_vol[cyl]) and float(t_s) >= float(fp.runtime_slotclose_charge_end_time_by_vol_s[cyl]) - 1.0e-15:
                fp.runtime_slotclose_charge_active_by_vol[cyl] = 0
    if not (free_piston_uses_slot_closure_lambda(bundle) or free_piston_uses_vapor_injector(bundle)):
        _update_hcci_diesel_autoignition_state(bundle, t_s, y_state)
        return
    fp = bundle.free_piston
    for cyl_idx in getattr(bundle, 'cylinder_indices', []):
        cyl = int(cyl_idx)
        if not free_piston_cylinder_uses_latched_fuel(bundle, cyl):
            continue
        x_m, v_m_per_s = _local_piston_kinematics_for_volume(bundle, y_state, cyl)
        area_sum_m2 = _cylinder_slot_area_sum_m2(bundle, x_m, cyl)
        fp.runtime_last_slot_area_by_vol_m2[cyl] = float(area_sum_m2)
        if cyl == int(bundle.cylinder_indices[0]):
            fp.runtime_last_slot_area_sum_m2 = float(area_sum_m2)

        if area_sum_m2 > _slot_open_threshold_m2(fp, cyl):
            fp.runtime_slots_were_open_by_vol[cyl] = 1
            fp.runtime_latch_valid_by_vol[cyl] = 0
            if cyl == int(bundle.cylinder_indices[0]):
                fp.runtime_slots_were_open = True
                fp.runtime_latch_valid = False
            continue

        if not (
            bool(fp.runtime_slots_were_open_by_vol[cyl])
            and area_sum_m2 <= _slot_closed_threshold_m2(fp, cyl)
            and v_m_per_s < -_compression_velocity_threshold_m_per_s(fp, cyl)
        ):
            continue

        air_idx = int(bundle.state_layout.air_mass_index(cyl))
        cylinder_air_mass_kg = float(y_state[air_idx])
        fuel_mass_kg, energy_J = compute_lambda_energy_from_cylinder_mass(cylinder_air_mass_kg, bundle, cyl)
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
        if _cylinder_uses_slot_closure_lambda(bundle, cyl):
            duration_s = float(getattr(bundle.simulation, 'dt_s', 0.0))
            _arm_slotclose_charge(fp, t_s, fuel_mass_kg, duration_s)
            fp.runtime_slotclose_charge_active_by_vol[cyl] = 1 if fuel_mass_kg > 0.0 and duration_s > 0.0 else 0
            fp.runtime_slotclose_charge_time_by_vol_s[cyl] = float(t_s)
            fp.runtime_slotclose_charge_end_time_by_vol_s[cyl] = float(t_s + duration_s)
            fp.runtime_slotclose_charge_target_fuel_by_vol_kg[cyl] = fuel_mass_kg
            fp.runtime_slotclose_charge_rate_by_vol_kg_per_s[cyl] = fuel_mass_kg / duration_s if duration_s > 0.0 else 0.0
        if _cylinder_uses_vapor_injector(bundle, cyl):
            _arm_vapor_injector(fp, t_s, fuel_mass_kg, cyl)
    _update_hcci_diesel_autoignition_state(bundle, t_s, y_state)


def replay_free_piston_combustion_latch_series(bundle, y: np.ndarray, cylinder_idx: int | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = int(y.shape[1])
    mass_hist = np.zeros(n, dtype=np.float64)
    fuel_hist = np.zeros(n, dtype=np.float64)
    energy_hist = np.zeros(n, dtype=np.float64)
    area_hist = np.zeros(n, dtype=np.float64)
    if not (free_piston_uses_slot_closure_lambda(bundle) or free_piston_uses_vapor_injector(bundle)):
        return mass_hist, fuel_hist, energy_hist, area_hist

    fp = bundle.free_piston
    slots_were_open = False
    latch_valid = False
    latched_mass = 0.0
    latched_fuel = 0.0
    latched_energy = 0.0
    cyl_idx = int(cylinder_idx) if cylinder_idx is not None else int(bundle.cylinder_indices[0])
    if not free_piston_cylinder_uses_latched_fuel(bundle, cyl_idx):
        return mass_hist, fuel_hist, energy_hist, area_hist
    air_idx = int(bundle.state_layout.air_mass_index(cyl_idx))
    for k in range(n):
        x_m, v_m_per_s = _local_piston_kinematics_for_volume(bundle, y[:, k], cyl_idx)
        area_sum_m2 = _cylinder_slot_area_sum_m2(bundle, x_m, cyl_idx)
        area_hist[k] = area_sum_m2
        if area_sum_m2 > _slot_open_threshold_m2(fp, cyl_idx):
            slots_were_open = True
            latch_valid = False
        elif (
            slots_were_open
            and area_sum_m2 <= _slot_closed_threshold_m2(fp, cyl_idx)
            and v_m_per_s < -_compression_velocity_threshold_m_per_s(fp, cyl_idx)
        ):
            latched_mass = float(y[air_idx, k])
            latched_fuel, latched_energy = compute_lambda_energy_from_cylinder_mass(latched_mass, bundle, cyl_idx)
            latch_valid = True
            slots_were_open = False
        elif (
            k == 0 and area_sum_m2 <= _slot_closed_threshold_m2(fp, cyl_idx)
            and v_m_per_s < -_compression_velocity_threshold_m_per_s(fp, cyl_idx)
        ):
            latched_mass = float(y[air_idx, k])
            latched_fuel, latched_energy = compute_lambda_energy_from_cylinder_mass(latched_mass, bundle, cyl_idx)
            latch_valid = True
        if latch_valid:
            mass_hist[k] = latched_mass
            fuel_hist[k] = latched_fuel
            energy_hist[k] = latched_energy
    return mass_hist, fuel_hist, energy_hist, area_hist
