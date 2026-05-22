from __future__ import annotations

from pathlib import Path

import numpy as np

from thermo0d.config.constants import CombCol, CombDurationMode, FeatureCol, VolumeCol, VolumeType
from thermo0d.model.free_piston.forces import compute_load_info
from thermo0d.model.free_piston.geometry import (
    bounce_volume_from_position,
    cylinder_distance_from_tdc,
    cylinder_volume_from_position,
    free_piston_equivalent_linear_kinematics,
    free_piston_local_cycle_angle_deg,
    free_piston_local_cycle_angle_rate_deg_s,
    free_piston_reference_is_active,
)
from thermo0d.model.free_piston.thermo import pressure_from_state, temperature_from_state
from thermo0d.output.exporters import CsvExporter, ExcelExporter
from thermo0d.output.service import PostprocessingArtifacts, PostprocessingService
from thermo0d.physics.combustion import combustion_duration_mode_from_row, vibe_heat_release_rate, vibe_time_heat_release_rate_with_total_energy
from thermo0d.physics.composition import burned_fraction_0to1, unburned_mass_kg
from thermo0d.physics.quellen_props import lambda_from_air_and_fuel_mass, properties_from_mass_energy_components_quellen

try:
    from thermo0d.model.free_piston.combustion_latch import free_piston_combustion_enabled, free_piston_uses_slot_closure_lambda, free_piston_uses_vapor_injector, replay_free_piston_combustion_latch_series, replay_free_piston_time_combustion_series
except Exception:  # pragma: no cover - compatibility for project states without latch patch
    free_piston_combustion_enabled = None
    free_piston_uses_slot_closure_lambda = None
    free_piston_uses_vapor_injector = None
    replay_free_piston_combustion_latch_series = None
    replay_free_piston_time_combustion_series = None


F_COMB = int(FeatureCol.COMBUSTION)
B_FUEL = int(CombCol.FUEL_MASS_PER_CYCLE)
B_LHV = int(CombCol.LHV)
B_REF = int(CombCol.REF_TYPE)


def _resolve_output_path(config_path: Path, configured_outdir: str | None, configured_path: str | None, fallback_name: str) -> Path:
    from thermo0d.app.paths import PathManager
    return PathManager.resolve_output_file(config_path, configured_outdir=configured_outdir, configured_path=configured_path, fallback_name=fallback_name)


def _stateful_bounce_index(bundle) -> int:
    for i in range(int(bundle.vol_matrix.shape[0])):
        if int(bundle.vol_matrix[i, VolumeCol.TYPE]) == int(VolumeType.BOUNCE_CHAMBER):
            return i
    return -1


def _replay_combustion_latch_history(bundle, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = int(y.shape[1])
    zeros = np.zeros(n, dtype=np.float64)
    if free_piston_combustion_enabled is None or not free_piston_combustion_enabled(bundle) or replay_free_piston_combustion_latch_series is None:
        return zeros.copy(), zeros.copy(), zeros.copy(), zeros.copy()
    try:
        return replay_free_piston_combustion_latch_series(bundle, y)
    except Exception:
        return zeros.copy(), zeros.copy(), zeros.copy(), zeros.copy()


def _lambda_from_air_and_fuel(air_mass_kg: float, fuel_mass_kg: float, stoich_afr_kg_air_per_kg_fuel: float) -> float:
    fuel = max(float(fuel_mass_kg), 0.0)
    afr_stoich = max(float(stoich_afr_kg_air_per_kg_fuel), 1.0e-18)
    if fuel <= 1.0e-18:
        return 0.0
    return float(max(float(air_mass_kg), 0.0) / (fuel * afr_stoich))


def _safe_mass_fraction(component_mass_kg: float, total_mass_kg: float) -> float:
    total = max(float(total_mass_kg), 1.0e-30)
    return float(max(float(component_mass_kg), 0.0) / total)


def _compute_cylinder_added_energy_W(
    bundle,
    t_s: float,
    x_m: float,
    v_m_per_s: float,
    *,
    latched_energy_J: float = 0.0,
    soc_time_s: float | None = None,
    soc_energy_J: float = 0.0,
) -> float:
    fp = bundle.free_piston
    if fp is None or bundle.feature_flags.size <= F_COMB or int(bundle.feature_flags[F_COMB]) != 1:
        return 0.0
    cylinder_idx = int(bundle.cylinder_indices[0])
    comb_idx = int(bundle.vol_matrix[cylinder_idx, VolumeCol.COMB_ROW])
    if comb_idx < 0:
        return 0.0

    comb_row = np.array(bundle.comb_matrix[comb_idx], dtype=np.float64, copy=True)
    if not free_piston_reference_is_active(int(comb_row[B_REF]), x_m, v_m_per_s, fp.x_min_m, fp.x_max_m):
        return 0.0

    duration_mode = int(combustion_duration_mode_from_row(comb_row))
    if duration_mode == int(CombDurationMode.TIME):
        if soc_time_s is None:
            return 0.0
        return float(
            vibe_time_heat_release_rate_with_total_energy(
                t_s,
                float(soc_time_s),
                float(comb_row[CombCol.DURATION_DEG]),
                float(comb_row[CombCol.A]),
                float(comb_row[CombCol.M]),
                float(soc_energy_J),
            )
        )

    q_total_override_J = float(latched_energy_J)
    if q_total_override_J > 0.0:
        comb_row[B_FUEL] = q_total_override_J
        comb_row[B_LHV] = 1.0

    cycle_deg = float(bundle.cycle_deg)
    dtheta_dt_global = float(cycle_deg / bundle.cycle_period_s) if float(bundle.cycle_period_s) > 1.0e-18 else 0.0
    theta_global_deg = (float(t_s) * dtheta_dt_global) % cycle_deg if cycle_deg > 1.0e-18 else 0.0
    theta_local_deg = free_piston_local_cycle_angle_deg(x_m, v_m_per_s, fp.x_min_m, fp.x_max_m, cycle_deg)
    dtheta_local_dt_deg_s = free_piston_local_cycle_angle_rate_deg_s(v_m_per_s, fp.x_min_m, fp.x_max_m, cycle_deg)
    return float(
        vibe_heat_release_rate(
            theta_local_deg,
            theta_global_deg,
            dtheta_local_dt_deg_s,
            dtheta_dt_global,
            comb_row,
            cycle_deg,
        )
    )


def build_free_piston_rows(bundle, t: np.ndarray, y: np.ndarray) -> list[dict[str, float | int]]:
    fp = bundle.free_piston
    if fp is None:
        raise ValueError('bundle.free_piston must be present for free-piston postprocessing')
    bounce_idx = _stateful_bounce_index(bundle)
    m_idx = int(bundle.state_layout.mass_index(bundle.cylinder_indices[0]))
    u_idx = int(bundle.state_layout.energy_index(bundle.cylinder_indices[0]))
    b_idx = int(bundle.state_layout.burned_mass_index(bundle.cylinder_indices[0]))
    x_idx = int(fp.x_state_index)
    v_idx = int(fp.v_state_index)
    cv_default = float(bundle.gas_props[1])
    cp_default = float(bundle.gas_props[0])
    gas_constant_default = float(bundle.gas_props[2])
    kappa_default = float(bundle.gas_props[3])
    use_promo_thermo = bundle.gas_props.shape[0] > 4 and float(bundle.gas_props[4]) >= 0.5
    rows: list[dict[str, float | int]] = []
    latched_mass_hist, latched_fuel_hist, latched_energy_hist, slot_area_hist = _replay_combustion_latch_history(bundle, y)
    use_latched_fuel = (
        (free_piston_uses_slot_closure_lambda is not None and bool(free_piston_uses_slot_closure_lambda(bundle)))
        or (free_piston_uses_vapor_injector is not None and bool(free_piston_uses_vapor_injector(bundle)))
    )
    time_vibe_energy_hist = latched_energy_hist if use_latched_fuel else None
    if replay_free_piston_time_combustion_series is not None:
        soc_time_hist, soc_energy_hist, _soc_active_hist = replay_free_piston_time_combustion_series(bundle, np.asarray(t, dtype=np.float64), np.asarray(y, dtype=np.float64), time_vibe_energy_hist)
    else:
        soc_time_hist = np.zeros(int(t.size), dtype=np.float64)
        soc_energy_hist = np.zeros(int(t.size), dtype=np.float64)
    for k in range(int(t.size)):
        state_k = y[:, k]
        mass_kg = float(bundle.state_layout.gas_mass_from_state(state_k, int(bundle.cylinder_indices[0])))
        internal_energy_J = float(y[u_idx, k])
        burned_mass_kg = float(bundle.state_layout.burned_mass_from_state(state_k, int(bundle.cylinder_indices[0])))
        residual_mass_kg = float(bundle.state_layout.residual_mass_from_state(state_k, int(bundle.cylinder_indices[0])))
        fresh_burned_mass_kg = float(bundle.state_layout.fresh_burned_mass_from_state(state_k, int(bundle.cylinder_indices[0])))
        air_mass_kg = float(bundle.state_layout.air_mass_from_state(state_k, int(bundle.cylinder_indices[0])))
        liquid_fuel_mass_kg = float(bundle.state_layout.liquid_fuel_mass_from_state(state_k, int(bundle.cylinder_indices[0])))
        fuel_vapor_mass_kg = float(bundle.state_layout.fuel_vapor_mass_from_state(state_k, int(bundle.cylinder_indices[0])))
        q = float(y[x_idx, k])
        q_dot = float(y[v_idx, k])
        x_m, v_m_per_s = free_piston_equivalent_linear_kinematics(
            q,
            q_dot,
            1.0,
            kinematics_type=str(getattr(fp, 'kinematics_type', 'linear') or 'linear'),
            x_min_m=float(fp.x_min_m),
            x_max_m=float(fp.x_max_m),
            angle_min_rad=float(getattr(fp, 'rotary_angle_min_rad', 0.0) or 0.0),
            angle_max_rad=float(getattr(fp, 'rotary_angle_max_rad', 0.0) or 0.0),
            effective_radius_m=float(getattr(fp, 'rotary_effective_radius_m', 1.0) or 1.0),
        )
        cylinder_distance_from_tdc_m = cylinder_distance_from_tdc(x_m, fp.x_min_m, fp.x_max_m)
        cylinder_volume_m3 = cylinder_volume_from_position(fp.clearance_volume_m3, fp.piston_area_m2, x_m, fp.x_min_m, fp.x_max_m)
        bounce_volume_m3 = bounce_volume_from_position(fp.bounce_chamber_volume0_m3, fp.bounce_area_m2, x_m, fp.x_min_m, fp.x_max_m)
        afr_eff = float(getattr(fp, 'combustion_afr_stoich_kg_air_per_kg_fuel', 14.5) or 14.5)
        thermo_lambda = lambda_from_air_and_fuel_mass(air_mass_kg, fuel_vapor_mass_kg, afr_eff)
        cylinder_temperature_K, cylinder_cp, cylinder_cv, cylinder_R, cylinder_kappa = properties_from_mass_energy_components_quellen(mass_kg, internal_energy_J, air_mass_kg, fuel_vapor_mass_kg, burned_mass_kg, cv_default)
        cylinder_pressure_Pa = pressure_from_state(mass_kg, internal_energy_J, cylinder_volume_m3, cylinder_R, cylinder_cv)
        if bounce_idx >= 0:
            bounce_m_idx = int(bundle.state_layout.mass_index(bounce_idx))
            bounce_u_idx = int(bundle.state_layout.energy_index(bounce_idx))
            bounce_state_k = y[:, k]
            bounce_mass_kg = float(bundle.state_layout.gas_mass_from_state(bounce_state_k, bounce_idx))
            bounce_internal_energy_J = float(y[bounce_u_idx, k])
            bounce_lambda = lambda_from_air_and_fuel_mass(float(bundle.state_layout.air_mass_from_state(bounce_state_k, bounce_idx)), float(bundle.state_layout.fuel_vapor_mass_from_state(bounce_state_k, bounce_idx)), float(bundle.combustion_afr_stoich_by_vol[bounce_idx]) if getattr(bundle, 'combustion_afr_stoich_by_vol', None) is not None and bounce_idx < int(bundle.combustion_afr_stoich_by_vol.shape[0]) else 14.5)
            bounce_air_kg = float(bundle.state_layout.air_mass_from_state(bounce_state_k, bounce_idx))
            bounce_burned_kg = float(bundle.state_layout.burned_mass_from_state(bounce_state_k, bounce_idx))
            bounce_fuel_vapor_kg = float(bundle.state_layout.fuel_vapor_mass_from_state(bounce_state_k, bounce_idx))
            bounce_temperature_K, bounce_cp, bounce_cv, bounce_R, bounce_kappa = properties_from_mass_energy_components_quellen(bounce_mass_kg, bounce_internal_energy_J, bounce_air_kg, bounce_fuel_vapor_kg, bounce_burned_kg, cv_default)
            bounce_pressure_Pa = pressure_from_state(bounce_mass_kg, bounce_internal_energy_J, bounce_volume_m3, bounce_R, bounce_cv)
        else:
            bounce_temperature_K = float('nan')
            bounce_pressure_Pa = float(fp.bounce_p0_Pa * (fp.bounce_chamber_volume0_m3 / bounce_volume_m3) ** fp.bounce_polytropic_exponent)
        force_gas_N = -cylinder_pressure_Pa * fp.piston_area_m2
        force_bounce_N = bounce_pressure_Pa * fp.bounce_area_m2
        if abs(v_m_per_s) < 1.0e-15:
            friction_force = 0.0
        else:
            friction_force = -(fp.friction_fc_N * np.copysign(1.0, v_m_per_s) + fp.friction_cv_Ns_per_m * v_m_per_s)
        load_info = compute_load_info(
            fp.load_model,
            fp.load_damping_Ns_per_m,
            v_m_per_s,
            x_m=x_m,
            x_min_m=fp.x_min_m,
            x_max_m=fp.x_max_m,
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
        load_force_signed = float(load_info.force_signed_N)
        load_force = -load_force_signed
        force_net_N = force_gas_N + force_bounce_N + friction_force + load_force
        if str(getattr(fp, 'kinematics_type', 'linear') or 'linear') == 'oscillating_rotary':
            radius = max(float(getattr(fp, 'rotary_effective_radius_m', 1.0) or 1.0), 1.0e-18)
            inertia = max(float(getattr(fp, 'rotary_inertia_kg_m2', fp.moving_mass_kg) or fp.moving_mass_kg), 1.0e-30)
            equivalent_accel_m_per_s2 = force_net_N * radius * radius / inertia
        else:
            equivalent_accel_m_per_s2 = force_net_N / max(float(fp.moving_mass_kg), 1.0e-30)
        added_energy_W = _compute_cylinder_added_energy_W(
            bundle,
            float(t[k]),
            x_m,
            v_m_per_s,
            latched_energy_J=float(latched_energy_hist[k]),
            soc_time_s=float(soc_time_hist[k]) if float(soc_energy_hist[k]) > 0.0 else None,
            soc_energy_J=float(soc_energy_hist[k]),
        )
        latched_air_mass_kg = float(latched_mass_hist[k])
        latched_fuel_mass_kg = float(latched_fuel_hist[k])
        latched_energy_J = float(latched_energy_hist[k])
        lambda_value = _lambda_from_air_and_fuel(
            latched_air_mass_kg,
            latched_fuel_mass_kg,
            getattr(fp, 'combustion_afr_stoich_kg_air_per_kg_fuel', 0.0),
        )
        total_inventory_mass_kg = mass_kg + liquid_fuel_mass_kg
        unburned_mass_kg_value = float(unburned_mass_kg(mass_kg, burned_mass_kg))
        rows.append({
            't_s': float(t[k]),
            'cycle_index': 0,
            'cylinder_m_kg': mass_kg,
            'cylinder_U_J': internal_energy_J,
            'cylinder_m_burned_kg': burned_mass_kg,
            'cylinder_m_residual_kg': residual_mass_kg,
            'cylinder_m_fresh_burned_kg': fresh_burned_mass_kg,
            'cylinder_m_air_kg': air_mass_kg,
            'cylinder_m_fuel_liquid_kg': liquid_fuel_mass_kg,
            'cylinder_m_fuel_vapor_kg': fuel_vapor_mass_kg,
            'cylinder_m_fuel_total_kg': fuel_vapor_mass_kg + liquid_fuel_mass_kg,
            'cylinder_m_inventory_total_kg': total_inventory_mass_kg,
            'cylinder_m_unburned_kg': unburned_mass_kg_value,
            'cylinder_burned_fraction_0to1': float(burned_fraction_0to1(mass_kg, burned_mass_kg)),
            'cylinder_share_air_0to1': _safe_mass_fraction(air_mass_kg, total_inventory_mass_kg),
            'cylinder_share_fuel_vapor_0to1': _safe_mass_fraction(fuel_vapor_mass_kg, total_inventory_mass_kg),
            'cylinder_share_fuel_liquid_0to1': _safe_mass_fraction(liquid_fuel_mass_kg, total_inventory_mass_kg),
            'cylinder_share_fuel_total_0to1': _safe_mass_fraction(fuel_vapor_mass_kg + liquid_fuel_mass_kg, total_inventory_mass_kg),
            'cylinder_injector_active_0or1': 1.0 if bool(getattr(bundle.free_piston, 'runtime_injector_active', False)) else 0.0,
            'cylinder_injector_rate_kg_per_s': float(getattr(bundle.free_piston, 'runtime_injector_rate_kg_per_s', 0.0) or 0.0),
            'cylinder_injector_target_fuel_mass_kg': float(getattr(bundle.free_piston, 'runtime_injector_target_fuel_mass_kg', 0.0) or 0.0),
            'cylinder_combustion_fuel_burn_rate_kg_per_s': float(getattr(bundle.free_piston, 'runtime_combustion_fuel_burn_rate_kg_per_s', 0.0) or 0.0),
            'cylinder_combustion_air_consumption_rate_kg_per_s': float(getattr(bundle.free_piston, 'runtime_combustion_air_consumption_rate_kg_per_s', 0.0) or 0.0),
            'cylinder_combustion_burned_production_rate_kg_per_s': float(getattr(bundle.free_piston, 'runtime_combustion_burned_production_rate_kg_per_s', 0.0) or 0.0),
            'cylinder_combustion_qdot_effective_W': float(getattr(bundle.free_piston, 'runtime_combustion_qdot_W', 0.0) or 0.0),
            'cylinder_share_burned_0to1': _safe_mass_fraction(burned_mass_kg, total_inventory_mass_kg),
            'cylinder_share_residual_0to1': _safe_mass_fraction(residual_mass_kg, total_inventory_mass_kg),
            'cylinder_share_fresh_burned_0to1': _safe_mass_fraction(fresh_burned_mass_kg, total_inventory_mass_kg),
            'cylinder_share_unburned_0to1': _safe_mass_fraction(unburned_mass_kg_value, total_inventory_mass_kg),
            'free_piston_x_m': x_m,
            'free_piston_distance_from_tdc_m': cylinder_distance_from_tdc_m,
            'free_piston_v_m_per_s': v_m_per_s,
            'free_piston_q': q,
            'free_piston_q_dot': q_dot,
            'cylinder_volume_m3': cylinder_volume_m3,
            'bounce_volume_m3': bounce_volume_m3,
            'cylinder_pressure_Pa': cylinder_pressure_Pa,
            'cylinder_temperature_K': cylinder_temperature_K,
            'cylinder_cp_J_per_kgK': float(cylinder_cp),
            'cylinder_cv_J_per_kgK': float(cylinder_cv),
            'cylinder_R_J_per_kgK': float(cylinder_R),
            'cylinder_kappa': float(cylinder_kappa),
            'cylinder_thermo_lambda': float(thermo_lambda),
            'bounce_pressure_Pa': bounce_pressure_Pa,
            'bounce_temperature_K': bounce_temperature_K,
            'bounce_cp_J_per_kgK': float(bounce_cp) if bounce_idx >= 0 else float('nan'),
            'bounce_cv_J_per_kgK': float(bounce_cv) if bounce_idx >= 0 else float('nan'),
            'bounce_R_J_per_kgK': float(bounce_R) if bounce_idx >= 0 else float('nan'),
            'bounce_kappa': float(bounce_kappa) if bounce_idx >= 0 else float('nan'),
            'free_piston_F_gas_N': force_gas_N,
            'free_piston_F_bounce_N': force_bounce_N,
            'free_piston_F_friction_N': friction_force,
            'free_piston_F_load_N': load_force,
            'free_piston_F_net_N': force_net_N,
            'free_piston_a_m_per_s2': equivalent_accel_m_per_s2,
            'free_piston_generator_power_W': float(load_info.mechanical_power_W),
            'free_piston_generator_electrical_power_W': float(load_info.electrical_power_W),
            'free_piston_generator_damping_eff_Ns_per_m': float(load_info.effective_damping_Ns_per_m),
            'free_piston_generator_force_base_N': float(load_info.base_force_N),
            'free_piston_generator_force_power_N': float(load_info.power_force_N),
            'free_piston_generator_force_stop_N': float(load_info.stop_force_N),
            'free_piston_generator_distance_to_stop_m': float(load_info.distance_to_stop_m),
            'free_piston_generator_midstroke_weight': float(load_info.midstroke_weight_0to1),
            'cylinder_added_energy_W': float(added_energy_W),
            'cylinder_combustion_air_mass_latched_kg': latched_air_mass_kg,
            'cylinder_combustion_fuel_mass_latched_kg': latched_fuel_mass_kg,
            'cylinder_combustion_energy_latched_J': latched_energy_J,
            'cylinder_lambda': float(lambda_value),
            'free_piston_slot_area_sum_m2': float(slot_area_hist[k]),
            'free_piston_combustion_mass_latched_kg': latched_air_mass_kg,
            'free_piston_combustion_fuel_mass_latched_kg': latched_fuel_mass_kg,
            'free_piston_combustion_energy_latched_J': latched_energy_J,
            'free_piston_combustion_lambda': float(lambda_value),
        })
    return PostprocessingService._add_cycle_integrals(rows)


def run_free_piston_postprocessing(bundle, config_path: str | Path, t: np.ndarray, y: np.ndarray, *, excel: bool | None = None) -> PostprocessingArtifacts:
    cfg_path = Path(config_path).resolve()
    outdir = str(getattr(bundle.postprocessing, 'outdir', '') or '').strip() or None
    rows = build_free_piston_rows(bundle, t, y)
    csv_path_text = None
    excel_path_text = None
    if bool(getattr(bundle.postprocessing, 'csv_enabled', True)) and rows:
        csv_path = _resolve_output_path(cfg_path, outdir, getattr(bundle.postprocessing, 'csv_path', None), 'free_piston_out.csv')
        CsvExporter.write(csv_path, str(getattr(bundle.postprocessing, 'csv_separator', ';') or ';'), rows)
        csv_path_text = str(csv_path)
    effective_excel = bool(getattr(bundle.postprocessing, 'excel_enabled', False)) if excel is None else bool(excel)
    if effective_excel and rows:
        excel_path = _resolve_output_path(cfg_path, outdir, getattr(bundle.postprocessing, 'excel_path', None), 'free_piston_out.xlsx')
        ExcelExporter.write(excel_path, rows)
        excel_path_text = str(excel_path)
    return PostprocessingArtifacts(csv_path=csv_path_text, excel_path=excel_path_text, export_rows=rows, check_report_metrics=[])
