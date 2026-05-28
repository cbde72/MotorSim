from __future__ import annotations

import math

import numpy as np

from thermo0d.config.constants import AngleDomain, AngleReference, ConnCol, ConnectionType, FlowCoeffMode, SlotOpenMode, VolumeCol, VolumeType
from thermo0d.config.models import (
    CheckValveConnectionConfig,
    ConstantDischargeCoefficientsConfig,
    OrificeConnectionConfig,
    SlotConnectionConfig,
    TableDischargeCoefficientsConfig,
    ValveConnectionConfig,
)
from thermo0d.core.model_bundle import PlotLayoutEntryOptions, PostprocessingOptions, SimulationOptions
from thermo0d.physics.kinematics import piston_displacement_from_tdc


def compute_cycle_deg(cycle_type: str) -> float:
    return 360.0 if str(cycle_type) == '2t' else 720.0


def compute_cycle_period_s(cycle_deg: float, speed_rpm: float) -> float:
    return float(cycle_deg) / (6.0 * float(speed_rpm))


def build_gas_props(config) -> np.ndarray:
    kappa = float(config.gas_properties.cp_J_per_kgK) / float(config.gas_properties.cv_J_per_kgK)
    thermo_model = str(getattr(config.gas_properties, "thermo_model", "constant") or "constant")
    thermo_flag = 1.0 if thermo_model == "promo" else 0.0
    return np.array([
        float(config.gas_properties.cp_J_per_kgK),
        float(config.gas_properties.cv_J_per_kgK),
        float(config.gas_properties.R_J_per_kgK),
        kappa,
        thermo_flag,
    ], dtype=np.float64)


def build_gas_thermo_model(config) -> str:
    return str(getattr(config.gas_properties, "thermo_model", "constant") or "constant")


def build_feature_flags(config) -> np.ndarray:
    return np.array([
        int(config.features.mass_flow),
        int(config.features.wall_heat),
        int(config.features.combustion),
        int(config.features.evaporation),
        int(config.features.pv_work),
    ], dtype=np.int64)


def build_simulation_options(config, cycle_period_s: float) -> SimulationOptions:
    configured_simulationtime_s = float(config.simulation.simulationtime) if config.simulation.simulationtime is not None else None
    effective_total_cycles = int(config.simulation.total_cycles)
    if configured_simulationtime_s is not None and float(cycle_period_s) > 0.0:
        effective_total_cycles = max(
            effective_total_cycles,
            int(math.ceil(configured_simulationtime_s / float(cycle_period_s) - 1.0e-12)),
        )
    return SimulationOptions(
        dt_s=float(config.simulation.dt_s),
        total_cycles=effective_total_cycles,
        save_last_cycles=min(int(config.simulation.save_last_cycles), effective_total_cycles),
        simulationtime_s=configured_simulationtime_s,
        solver_kind=str(config.simulation.solver.kind),
        rtol=float(config.simulation.solver.rtol),
        atol=float(config.simulation.solver.atol),
    )


def build_postprocessing_options(config) -> PostprocessingOptions:
    if config.postprocessing.sampling.mode == 'time':
        sampling_step = float(config.postprocessing.sampling.step_s)
    elif config.postprocessing.sampling.mode == 'crank_angle':
        sampling_step = float(config.postprocessing.sampling.step_deg)
    else:
        raise ValueError(f'Unsupported postprocessing sampling mode: {config.postprocessing.sampling.mode}')

    return PostprocessingOptions(
        outdir=config.postprocessing.outdir,
        auto_update_initial_conditions=bool(config.postprocessing.auto_update_initial_conditions),
        csv_enabled=bool(config.postprocessing.csv_enabled),
        csv_path=str(config.postprocessing.csv_path),
        csv_separator=str(config.postprocessing.csv_separator),
        csv_export_layout=config.postprocessing.csv_export_layout,
        csv_export_mode=str(config.postprocessing.csv_export_mode),
        csv_export_missing_layout=str(config.postprocessing.csv_export_missing_layout),
        csv_export_unknown_signals=str(config.postprocessing.csv_export_unknown_signals),
        excel_enabled=bool(config.postprocessing.excel_enabled),
        excel_path=str(config.postprocessing.excel_path),
        sampling_mode=str(config.postprocessing.sampling.mode),
        sampling_step=sampling_step,
        final_cycle_uniform_angle_export_enabled=bool(config.postprocessing.final_cycle_uniform_angle_export.enabled),
        final_cycle_uniform_angle_export_step_deg=float(config.postprocessing.final_cycle_uniform_angle_export.step_deg),
        free_piston_last_ut_ot_ut_export_enabled=bool(config.postprocessing.free_piston_last_ut_ot_ut_export.enabled),
        free_piston_last_ut_ot_ut_export_step_deg=float(config.postprocessing.free_piston_last_ut_ot_ut_export.step_deg),
        free_piston_last_ut_ot_ut_export_axis_min_deg=float(config.postprocessing.free_piston_last_ut_ot_ut_export.axis_min_deg),
        free_piston_last_ut_ot_ut_export_axis_max_deg=float(config.postprocessing.free_piston_last_ut_ot_ut_export.axis_max_deg),
        check_report_enabled=bool(config.postprocessing.check_report.enabled),
        check_report_html_enabled=bool(config.postprocessing.check_report.html_enabled),
        plots_enabled=bool(config.postprocessing.plots.enabled),
        plots_source=str(config.postprocessing.plots.source),
        plots_output_dir=config.postprocessing.plots.output_dir,
        plot_layout_auto_create_defaults=bool(config.postprocessing.plots.layouts.auto_create_defaults),
        plot_layout_entries=[
            PlotLayoutEntryOptions(enabled=bool(entry.enabled), path=str(entry.path), prefix=str(entry.prefix))
            for entry in config.postprocessing.plots.layouts.entries
        ],
        console_run_summary_enabled=bool(config.postprocessing.console.run_summary.enabled),
        console_cycle_summary_enabled=bool(config.postprocessing.console.cycle_summary.enabled),
        console_check_report_enabled=bool(config.postprocessing.console.check_report.enabled),
        console_geometry_enabled=bool(config.postprocessing.console.geometry.enabled),
    )


def build_environment_buffers(n_volumes: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    n = int(n_volumes)
    return (
        np.zeros(n, dtype=np.int64),
        np.zeros(n, dtype=np.float64),
        np.zeros(n, dtype=np.float64),
    )


def assign_state_from_mass_and_temperature(
    y_init: np.ndarray,
    *,
    mass_index: int,
    energy_index: int,
    mass_kg: float,
    temperature_K: float,
    cv_J_per_kgK: float,
) -> None:
    mass = float(mass_kg)
    y_init[int(mass_index)] = mass
    y_init[int(energy_index)] = mass * float(cv_J_per_kgK) * float(temperature_K)


def build_connection_tables(
    builder,
    *,
    config,
    vol_matrix: np.ndarray,
    kin_matrix: np.ndarray,
    name_to_index: dict[str, int],
    allow_valves: bool = True,
    allow_slot_by_angle: bool = True,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, list[str]]:
    lift_rows: list[np.ndarray] = []
    alpha_rows: list[np.ndarray] = []
    cd_rows: list[np.ndarray] = []
    conn_rows: list[list[float]] = []
    connection_names: list[str] = []

    def append_table(store: list[np.ndarray], data: np.ndarray) -> tuple[int, int]:
        start = sum(arr.shape[0] for arr in store)
        store.append(data)
        return start, data.shape[0]

    for conn in config.connections:
        row = np.full((len(ConnCol),), -1.0, dtype=np.float64)
        row[ConnCol.FROM_VOL] = name_to_index[conn.from_volume]
        row[ConnCol.TO_VOL] = name_to_index[conn.to_volume]

        if isinstance(conn, ValveConnectionConfig):
            if not allow_valves:
                raise ValueError(f'Connection {conn.name}: valve connections are not enabled for this architecture')
            row[ConnCol.TYPE] = float(ConnectionType.VALVE)
            row[ConnCol.PRIMARY_DIM] = 0.0
            row[ConnCol.SECONDARY_DIM] = 0.0
            row[ConnCol.OPEN_VALUE] = conn.opening_angle_deg
            row[ConnCol.OPEN_MODE] = 0.0
            row[ConnCol.REF_TYPE] = float(builder._ref_enum(conn.opening_reference))
            row[ConnCol.ANGLE_DOMAIN] = float(AngleDomain.CRANK if conn.profile_angle_domain == 'crank' else AngleDomain.CAM)
            row[ConnCol.LIFT_SCALE] = conn.lift_scale
            row[ConnCol.LASH] = conn.lash_m
            row[ConnCol.N_HOLES] = 1.0
            row[ConnCol.ENTRANCE_ANGLE_DEG] = 0.0
            row[ConnCol.OPEN_FILLET_RADIUS] = 0.0
            row[ConnCol.FULL_FILLET_RADIUS] = 0.0
            row[ConnCol.CD_MODE] = -1.0
            row[ConnCol.CD_FORWARD] = -1.0
            row[ConnCol.CD_REVERSE] = -1.0
            row[ConnCol.CD_TABLE_START] = -1.0
            row[ConnCol.CD_TABLE_LEN] = 0.0
            from_idx = name_to_index[conn.from_volume]
            to_idx = name_to_index[conn.to_volume]
            cyl_idx = from_idx if int(vol_matrix[from_idx, VolumeCol.TYPE]) == VolumeType.CYLINDER else to_idx
            kin_idx = int(vol_matrix[cyl_idx, VolumeCol.KIN_ROW])
            if kin_idx < 0:
                raise ValueError(f'Valve {conn.name} needs at least one cylinder side with kinematic reference data')
            bore = float(kin_matrix[kin_idx, 1])
            row[ConnCol.REF_FLOW_AREA] = 0.25 * np.pi * bore * bore

            lift_data = builder._load_csv_table((builder.config_dir / conn.lift_file).resolve(), expected_cols=2, table_kind='valve_lift')
            alpha_data = builder._load_csv_table((builder.config_dir / conn.alpha_k_file).resolve(), expected_cols=3, table_kind='valve_alpha')
            profile_start, profile_len = append_table(lift_rows, lift_data)
            alpha_start, alpha_len = append_table(alpha_rows, alpha_data)
            row[ConnCol.PROFILE_START] = profile_start
            row[ConnCol.PROFILE_LEN] = profile_len
            row[ConnCol.ALPHA_START] = alpha_start
            row[ConnCol.ALPHA_LEN] = alpha_len

        elif isinstance(conn, SlotConnectionConfig):
            row[ConnCol.TYPE] = float(ConnectionType.SLOT)
            row[ConnCol.PRIMARY_DIM] = conn.resolved_width_m
            row[ConnCol.SECONDARY_DIM] = conn.resolved_height_m
            row[ConnCol.REF_TYPE] = float(AngleReference.ABSOLUTE)
            row[ConnCol.ANGLE_DOMAIN] = float(AngleDomain.CRANK)
            row[ConnCol.LIFT_SCALE] = 1.0
            row[ConnCol.LASH] = 0.0
            row[ConnCol.N_HOLES] = float(conn.number_of_identical_holes)
            row[ConnCol.ENTRANCE_ANGLE_DEG] = conn.entrance_angle_deg
            row[ConnCol.OPEN_FILLET_RADIUS] = conn.open_fillet_radius_m
            row[ConnCol.FULL_FILLET_RADIUS] = conn.full_fillet_radius_m
            row[ConnCol.PROFILE_START] = -1.0
            row[ConnCol.PROFILE_LEN] = 0.0
            row[ConnCol.ALPHA_START] = -1.0
            row[ConnCol.ALPHA_LEN] = 0.0

            cyl_idx = int(row[ConnCol.FROM_VOL]) if int(vol_matrix[int(row[ConnCol.FROM_VOL]), VolumeCol.TYPE]) == VolumeType.CYLINDER else int(row[ConnCol.TO_VOL])
            if int(vol_matrix[cyl_idx, VolumeCol.TYPE]) != VolumeType.CYLINDER:
                raise ValueError(f'Slot {conn.name} needs at least one cylinder side')
            kin_idx = int(vol_matrix[cyl_idx, VolumeCol.KIN_ROW])
            open_distance = conn.resolved_distance_from_tdc_m
            if conn.opening_mode == 'by_angle':
                if not allow_slot_by_angle:
                    raise ValueError(f'Slot {conn.name}: opening_mode=by_angle is not enabled for this architecture')
                if kin_idx < 0:
                    raise ValueError(f'Slot {conn.name}: opening_mode=by_angle requires cylinder kinematic reference data')
                open_theta_deg = float(conn.opening_angle_deg)
                open_distance = float(piston_displacement_from_tdc(kin_matrix[kin_idx], open_theta_deg))
                row[ConnCol.OPEN_MODE] = float(SlotOpenMode.BY_ANGLE)
            else:
                row[ConnCol.OPEN_MODE] = float(SlotOpenMode.BY_DISTANCE)
            row[ConnCol.OPEN_VALUE] = float(open_distance)

            if isinstance(conn.discharge_coefficients, ConstantDischargeCoefficientsConfig):
                row[ConnCol.CD_MODE] = float(FlowCoeffMode.CONSTANT)
                row[ConnCol.CD_FORWARD] = conn.discharge_coefficients.forward_cd
                row[ConnCol.CD_REVERSE] = conn.discharge_coefficients.reverse_cd
                row[ConnCol.CD_TABLE_START] = -1.0
                row[ConnCol.CD_TABLE_LEN] = 0.0
            elif isinstance(conn.discharge_coefficients, TableDischargeCoefficientsConfig):
                row[ConnCol.CD_MODE] = float(FlowCoeffMode.TABLE)
                row[ConnCol.CD_FORWARD] = -1.0
                row[ConnCol.CD_REVERSE] = -1.0
                cd_data = builder._load_csv_table((builder.config_dir / conn.discharge_coefficients.table_file).resolve(), expected_cols=3)
                cd_start, cd_len = append_table(cd_rows, cd_data)
                row[ConnCol.CD_TABLE_START] = cd_start
                row[ConnCol.CD_TABLE_LEN] = cd_len
            else:
                raise TypeError('Unsupported slot discharge_coefficients model')
            row[ConnCol.REF_FLOW_AREA] = 0.0

        elif isinstance(conn, OrificeConnectionConfig):
            row[ConnCol.TYPE] = float(ConnectionType.ORIFICE)
            row[ConnCol.PRIMARY_DIM] = conn.resolved_area_m2
            row[ConnCol.SECONDARY_DIM] = 0.0
            row[ConnCol.OPEN_VALUE] = 0.0
            row[ConnCol.OPEN_MODE] = 0.0
            row[ConnCol.REF_TYPE] = float(AngleReference.ABSOLUTE)
            row[ConnCol.ANGLE_DOMAIN] = float(AngleDomain.CRANK)
            row[ConnCol.LIFT_SCALE] = 1.0
            row[ConnCol.LASH] = 0.0
            row[ConnCol.N_HOLES] = 1.0
            row[ConnCol.ENTRANCE_ANGLE_DEG] = 0.0
            row[ConnCol.OPEN_FILLET_RADIUS] = 0.0
            row[ConnCol.FULL_FILLET_RADIUS] = 0.0
            row[ConnCol.PROFILE_START] = -1.0
            row[ConnCol.PROFILE_LEN] = 0.0
            row[ConnCol.ALPHA_START] = -1.0
            row[ConnCol.ALPHA_LEN] = 0.0
            row[ConnCol.CD_MODE] = float(FlowCoeffMode.CONSTANT)
            row[ConnCol.CD_FORWARD] = conn.forward_cd
            row[ConnCol.CD_REVERSE] = conn.reverse_cd
            row[ConnCol.CD_TABLE_START] = -1.0
            row[ConnCol.CD_TABLE_LEN] = 0.0
            row[ConnCol.REF_FLOW_AREA] = conn.resolved_area_m2
        elif isinstance(conn, CheckValveConnectionConfig):
            row[ConnCol.TYPE] = float(ConnectionType.CHECK_VALVE)
            row[ConnCol.PRIMARY_DIM] = conn.resolved_area_m2
            row[ConnCol.SECONDARY_DIM] = 0.0
            row[ConnCol.OPEN_VALUE] = conn.cracking_pressure_Pa
            row[ConnCol.OPEN_MODE] = 0.0
            row[ConnCol.REF_TYPE] = float(AngleReference.ABSOLUTE)
            row[ConnCol.ANGLE_DOMAIN] = float(AngleDomain.CRANK)
            row[ConnCol.LIFT_SCALE] = 1.0
            row[ConnCol.LASH] = 0.0
            row[ConnCol.N_HOLES] = 1.0
            row[ConnCol.ENTRANCE_ANGLE_DEG] = 0.0
            row[ConnCol.OPEN_FILLET_RADIUS] = 0.0
            row[ConnCol.FULL_FILLET_RADIUS] = 0.0
            row[ConnCol.PROFILE_START] = -1.0
            row[ConnCol.PROFILE_LEN] = 0.0
            row[ConnCol.ALPHA_START] = -1.0
            row[ConnCol.ALPHA_LEN] = 0.0
            row[ConnCol.CD_MODE] = float(FlowCoeffMode.CONSTANT)
            row[ConnCol.CD_FORWARD] = conn.discharge_coefficient
            row[ConnCol.CD_REVERSE] = 0.0
            row[ConnCol.CD_TABLE_START] = -1.0
            row[ConnCol.CD_TABLE_LEN] = 0.0
            row[ConnCol.REF_FLOW_AREA] = conn.resolved_area_m2
        else:
            raise TypeError(f'Unsupported connection config: {type(conn)!r}')

        conn_rows.append(row.tolist())
        connection_names.append(conn.name)

    conn_matrix = np.asarray(conn_rows, dtype=np.float64) if conn_rows else np.zeros((0, len(ConnCol)), dtype=np.float64)
    lift_table = np.vstack(lift_rows) if lift_rows else np.zeros((0, 2), dtype=np.float64)
    alpha_table = np.vstack(alpha_rows) if alpha_rows else np.zeros((0, 3), dtype=np.float64)
    cd_table = np.vstack(cd_rows) if cd_rows else np.zeros((0, 3), dtype=np.float64)
    return conn_matrix, lift_table, alpha_table, cd_table, connection_names
