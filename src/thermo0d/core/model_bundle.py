from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from thermo0d.core.state_layout import StateLayout


@dataclass(slots=True)
class SimulationOptions:
    dt_s: float
    total_cycles: int
    save_last_cycles: int
    simulationtime_s: float | None = None
    solver_kind: str = 'rk4'
    rtol: float = 1.0e-6
    atol: float = 1.0e-9



@dataclass(slots=True)
class FreePistonModelData:
    x0_m: float
    v0_m_per_s: float
    x_min_m: float
    x_max_m: float
    moving_mass_kg: float
    piston_diameter_m: float
    compression_ratio: float
    piston_area_m2: float
    clearance_volume_m3: float
    cylinder_pressure_Pa: float
    cylinder_temperature_K: float
    initial_cylinder_volume_m3: float
    initial_cylinder_mass_kg: float
    initial_cylinder_internal_energy_J: float
    bounce_pressure_Pa: float
    bounce_temperature_K: float
    friction_model: str
    friction_fc_N: float
    friction_cv_Ns_per_m: float
    load_model: str
    load_damping_Ns_per_m: float
    load_max_damping_Ns_per_m: float
    load_control_zone_m: float
    load_power_target_W: float
    load_efficiency_0to1: float
    load_min_velocity_m_per_s: float
    load_assist_velocity_threshold_m_per_s: float
    load_assist_force_N: float
    load_target_margin_m: float
    load_hard_margin_m: float
    load_stop_kp: float
    load_max_force_N: float
    scavenging_enabled: bool
    scavenging_model: str
    scavenging_factor: float
    scavenging_max_trapping_efficiency: float
    scavenging_short_circuit_start_ratio: float
    scavenging_short_circuit_slope: float
    scavenging_max_short_circuit_fraction: float
    scavenging_min_residual_fraction: float
    bounce_model: str
    bounce_chamber_diameter_m: float
    bounce_chamber_length_m: float
    bounce_compression_ratio: float
    bounce_chamber_cross_section_m2: float
    bounce_swept_volume_m3: float
    bounce_area_m2: float
    bounce_chamber_min_volume_m3: float
    bounce_chamber_volume0_m3: float
    bounce_p0_Pa: float
    bounce_polytropic_exponent: float
    x_state_index: int
    v_state_index: int
    mechanical_dofs: int = 1
    mechanical_x_state_indices: np.ndarray = field(default_factory=lambda: np.zeros(1, dtype=np.int64))
    mechanical_v_state_indices: np.ndarray = field(default_factory=lambda: np.zeros(1, dtype=np.int64))
    volume_mechanical_dof: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    volume_mechanical_sign: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    combustion_fueling_mode: str = 'fixed_energy'
    combustion_fueling_mode_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    combustion_lambda_target: float = 0.0
    combustion_afr_stoich_kg_air_per_kg_fuel: float = 14.5
    combustion_efficiency_0to1: float = 1.0
    combustion_lhv_J_per_kg: float = 0.0
    combustion_slot_open_threshold_m2: float = 1.0e-7
    combustion_slot_closed_threshold_m2: float = 1.0e-9
    combustion_compression_velocity_threshold_m_per_s: float = 0.02
    injector_duration_s: float = 0.0
    combustion_slot_open_threshold_by_vol_m2: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    combustion_slot_closed_threshold_by_vol_m2: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    combustion_compression_velocity_threshold_by_vol_m_per_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    injector_duration_by_vol_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    combustion_comb_idx: int = -1
    combustion_cylinder_slot_conn_indices: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    runtime_slots_were_open: bool = False
    runtime_latch_valid: bool = False
    runtime_latched_cylinder_mass_kg: float = 0.0
    runtime_latched_fuel_mass_kg: float = 0.0
    runtime_latched_energy_J: float = 0.0
    runtime_last_slot_area_sum_m2: float = 0.0
    runtime_time_combustion_initialized: bool = False
    runtime_time_combustion_armed: bool = False
    runtime_soc_active: bool = False
    runtime_soc_time_s: float = 0.0
    runtime_soc_end_time_s: float = 0.0
    runtime_soc_energy_J: float = 0.0
    runtime_injector_active: bool = False
    runtime_injector_time_s: float = 0.0
    runtime_injector_end_time_s: float = 0.0
    runtime_injector_target_fuel_mass_kg: float = 0.0
    runtime_injector_injected_mass_kg: float = 0.0
    runtime_injector_rate_kg_per_s: float = 0.0
    runtime_injector_active_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    runtime_injector_time_by_vol_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_injector_end_time_by_vol_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_injector_target_fuel_by_vol_kg: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_injector_injected_by_vol_kg: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_injector_rate_by_vol_kg_per_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_slotclose_charge_active: bool = False
    runtime_slotclose_charge_time_s: float = 0.0
    runtime_slotclose_charge_end_time_s: float = 0.0
    runtime_slotclose_charge_target_fuel_mass_kg: float = 0.0
    runtime_slotclose_charge_rate_kg_per_s: float = 0.0
    runtime_slots_were_open_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    runtime_latch_valid_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    runtime_latched_cylinder_mass_by_vol_kg: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_latched_fuel_mass_by_vol_kg: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_latched_energy_by_vol_J: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_last_slot_area_by_vol_m2: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_time_combustion_initialized_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    runtime_time_combustion_armed_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    runtime_soc_active_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    runtime_soc_time_by_vol_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_soc_end_time_by_vol_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_soc_energy_by_vol_J: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_slotclose_charge_active_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    runtime_slotclose_charge_time_by_vol_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_slotclose_charge_end_time_by_vol_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_slotclose_charge_rate_by_vol_kg_per_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_slotclose_charge_target_fuel_by_vol_kg: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_combustion_fuel_burn_rate_kg_per_s: float = 0.0
    runtime_combustion_air_consumption_rate_kg_per_s: float = 0.0
    runtime_combustion_burned_production_rate_kg_per_s: float = 0.0
    runtime_combustion_qdot_W: float = 0.0
    hcci_enabled_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.int64))
    hcci_tau_A_by_vol_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    hcci_pressure_exponent_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    hcci_activation_temperature_by_vol_K: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    hcci_reference_pressure_by_vol_Pa: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    hcci_reference_lambda_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    hcci_lambda_slowdown_exponent_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    hcci_residual_slowdown_factor_by_vol: np.ndarray = field(default_factory=lambda: np.ones(0, dtype=np.float64))
    hcci_start_temperature_min_by_vol_K: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    hcci_start_pressure_min_by_vol_Pa: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    hcci_max_ignition_delay_by_vol_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_hcci_integral_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_hcci_last_update_time_by_vol_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_hcci_tau_by_vol_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_scavenging_transfer_in_kg_per_s: float = 0.0
    runtime_scavenging_exhaust_out_kg_per_s: float = 0.0
    runtime_scavenging_burned_correction_kg_per_s: float = 0.0
    runtime_scavenging_short_circuit_fraction: float = 0.0
    runtime_scavenging_transfer_in_by_vol_kg_per_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_scavenging_exhaust_out_by_vol_kg_per_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_scavenging_burned_correction_by_vol_kg_per_s: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))
    runtime_scavenging_short_circuit_fraction_by_vol: np.ndarray = field(default_factory=lambda: np.zeros(0, dtype=np.float64))

@dataclass(slots=True)
class PlotLayoutEntryOptions:
    enabled: bool = True
    path: str = "plot.yaml"
    prefix: str = ""


@dataclass(slots=True)
class PostprocessingOptions:
    outdir: str | None = None
    auto_update_initial_conditions: bool = True
    csv_enabled: bool = True
    csv_path: str = "results/out.csv"
    csv_separator: str = ";"
    excel_enabled: bool = False
    excel_path: str = "results/out.xlsx"
    sampling_mode: str = "crank_angle"
    sampling_step: float = 1.0
    final_cycle_uniform_angle_export_enabled: bool = False
    final_cycle_uniform_angle_export_step_deg: float = 1.0
    free_piston_last_ut_ot_ut_export_enabled: bool = False
    free_piston_last_ut_ot_ut_export_step_deg: float = 1.0
    free_piston_last_ut_ot_ut_export_axis_min_deg: float = 0.0
    free_piston_last_ut_ot_ut_export_axis_max_deg: float = 360.0
    check_report_enabled: bool = True
    check_report_html_enabled: bool = False
    plots_enabled: bool = True
    plots_source: str = "last_cycle_uniform"
    plots_output_dir: str | None = None
    plot_layout_auto_create_defaults: bool = True
    plot_layout_entries: list[PlotLayoutEntryOptions] = field(default_factory=list)
    console_run_summary_enabled: bool = True
    console_cycle_summary_enabled: bool = True
    console_check_report_enabled: bool = True
    console_geometry_enabled: bool = True



@dataclass(slots=True)
class ModelBundle:
    y_init: np.ndarray
    vol_matrix: np.ndarray
    kin_matrix: np.ndarray
    conn_matrix: np.ndarray
    wall_matrix: np.ndarray
    comb_matrix: np.ndarray
    evap_matrix: np.ndarray
    lift_table: np.ndarray
    alpha_table: np.ndarray
    cd_table: np.ndarray
    gas_props: np.ndarray
    gas_thermo_model: str
    feature_flags: np.ndarray
    cycle_period_s: float
    cycle_deg: float
    volume_names: list[str]
    connection_names: list[str]
    cylinder_indices: list[int]
    simulation: SimulationOptions
    postprocessing: PostprocessingOptions
    architecture: str = "classic"
    state_layout: StateLayout | None = None
    free_piston: FreePistonModelData | None = None
    wall_ref_matrix: np.ndarray | None = None
    wall_ref_matrix_safe: np.ndarray | None = None
    wall_bore_by_vol: np.ndarray | None = None
    wall_ups_by_vol: np.ndarray | None = None
    jac_sparsity: object | None = None
    jac_color_groups: object | None = None
    environment_is_fixed: np.ndarray | None = None
    environment_pressures_pa: np.ndarray | None = None
    environment_temperatures_K: np.ndarray | None = None
    combustion_fuel_mass_by_vol: np.ndarray | None = None
    combustion_afr_stoich_by_vol: np.ndarray | None = None
    combustion_lambda_target_by_vol: np.ndarray | None = None
    combustion_efficiency_by_vol: np.ndarray | None = None
    combustion_lhv_by_vol: np.ndarray | None = None
