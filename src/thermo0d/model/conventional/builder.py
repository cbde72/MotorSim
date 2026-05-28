from __future__ import annotations

import numpy as np

from thermo0d.config.constants import (
    AngleDomain,
    AngleReference,
    CombCol,
    CombustionModel,
    CombDurationMode,
    CombStartMode,
    ConnCol,
    ConnectionType,
    CycleType,
    EvapCol,
    EvaporationModel,
    FlowCoeffMode,
    HeatTransferModel,
    KinCol,
    KinematicsType,
    SlotOpenMode,
    VolumeCol,
    VolumeType,
    WallCol,
    WallRefCol,
    WallTemperatureCol,
    WallTemperatureZone,
)
from thermo0d.config.models import (
    ConstantDischargeCoefficientsConfig,
    CylinderVolumeConfig,
    DisabledCombustionConfig,
    DisabledEvaporationConfig,
    DisabledSubmodelConfig,
    EnvironmentVolumeConfig,
    CycleAverageWallTemperatureConfig,
    OrificeConnectionConfig,
    PlenumVolumeConfig,
    SimpleEvaporationConfig,
    SlotConnectionConfig,
    TableDischargeCoefficientsConfig,
    ValveConnectionConfig,
    VibeCombustionConfig,
    WoschniHeatTransferConfig,
)
from thermo0d.core.model_bundle import ModelBundle
from thermo0d.core.state_layout import StateLayout
from thermo0d.compute.jacobian import build_rhs_jacobian_sparsity, greedy_color_columns
from thermo0d.physics.kinematics import piston_displacement_from_tdc
from thermo0d.physics.quellen_props import reduced_mixture_properties_from_temperature_quellen
from thermo0d.input.builder_common import (
    assign_state_from_mass_and_temperature,
    build_environment_buffers,
    build_feature_flags,
    build_gas_props,
    build_gas_thermo_model,
    build_postprocessing_options,
    build_simulation_options,
    build_connection_tables,
)


def _resolve_combustion_total_energy_J(combustion_cfg, nominal_stroke_m: float) -> float:
    if getattr(combustion_cfg, 'added_energy_per_cycle_J', None) is not None:
        q_total = float(combustion_cfg.added_energy_per_cycle_J)
    else:
        q_total = float(combustion_cfg.fuel_mass_per_cycle_kg) * float(combustion_cfg.lhv_J_per_kg)
    if getattr(combustion_cfg, 'energy_coupling', 'none') == 'stroke_ratio':
        ref = float(combustion_cfg.stroke_reference_m)
        exponent = float(getattr(combustion_cfg, 'stroke_exponent', 1.0))
        ratio = max(float(nominal_stroke_m), 0.0) / max(ref, 1.0e-12)
        q_total *= ratio ** exponent
    return q_total


def _wall_temperature_zones(cfg: CycleAverageWallTemperatureConfig):
    return (
        (WallTemperatureZone.CYLINDER, "cylinder", cfg.cylinder),
        (WallTemperatureZone.HEAD, "head", cfg.head),
        (WallTemperatureZone.PISTON, "piston", cfg.piston),
    )


def build_conventional_bundle(builder) -> ModelBundle:
    config = builder.config
    n_vol = len(config.volumes)
    cycle_type = builder._cycle_enum(config.engine.cycle_type)
    cycle_deg = 360.0 if cycle_type == CycleType.TWO_STROKE else 720.0
    cycle_period_s = cycle_deg / (6.0 * config.engine.speed_rpm)

    vol_matrix = np.full((n_vol, len(VolumeCol)), -1.0, dtype=np.float64)
    state_layout = StateLayout.classic(n_vol)
    y_init = np.zeros(state_layout.total_size, dtype=np.float64)
    volume_names: list[str] = []
    name_to_index: dict[str, int] = {}
    cylinder_indices: list[int] = []

    kin_rows: list[list[float]] = []
    wall_rows: list[list[float]] = []
    wall_ref_rows: list[list[float]] = []
    n_wall_zones = len(WallTemperatureZone)
    wall_temperature_state_index_by_vol = np.full((n_vol, n_wall_zones), -1, dtype=np.int64)
    wall_temperature_average_state_index_by_vol = np.full((n_vol, 2), -1, dtype=np.int64)
    wall_temperature_params_by_vol = np.zeros((n_vol, n_wall_zones, len(WallTemperatureCol)), dtype=np.float64)
    wall_temperature_initials: list[tuple[int, str, float]] = []
    wall_temperature_average_initials: list[tuple[int, str, float]] = []
    comb_rows: list[list[float]] = []
    evap_rows: list[list[float]] = []
    environment_is_fixed, environment_pressures_pa, environment_temperatures_K = build_environment_buffers(n_vol)
    combustion_fuel_mass_by_vol = np.zeros(n_vol, dtype=np.float64)
    combustion_afr_stoich_by_vol = np.full(n_vol, 14.5, dtype=np.float64)

    for i, vol in enumerate(config.volumes):
        volume_names.append(vol.name)
        name_to_index[vol.name] = i
        initial_mass_kg = builder._initial_mass_kg(vol)
        if isinstance(vol, EnvironmentVolumeConfig):
            y_init[state_layout.mass_index(i)] = 0.0
            y_init[state_layout.energy_index(i)] = 0.0
            y_init[state_layout.burned_mass_index(i)] = 0.0
        else:
            assign_state_from_mass_and_temperature(
                y_init,
                mass_index=state_layout.mass_index(i),
                energy_index=state_layout.energy_index(i),
                mass_kg=initial_mass_kg,
                temperature_K=vol.initial_temperature_K,
                cv_J_per_kgK=config.gas_properties.cv_J_per_kgK,
            )
            initial_burned_mass_kg = initial_mass_kg * builder._initial_burned_fraction_0to1(vol)
            y_init[state_layout.burned_mass_index(i)] = initial_burned_mass_kg

        if isinstance(vol, CylinderVolumeConfig):
            cylinder_indices.append(i)
            kin_row_idx = len(kin_rows)
            kin_rows.append([
                float(KinematicsType.CRANK_SLIDER),
                vol.kinematics.bore_m,
                vol.kinematics.stroke_m,
                vol.kinematics.conrod_m,
                vol.kinematics.compression_ratio,
                vol.kinematics.phase_deg,
                config.engine.speed_rpm,
                cycle_deg,
            ])
            vol_matrix[i, VolumeCol.TYPE] = float(VolumeType.CYLINDER)
            vol_matrix[i, VolumeCol.KIN_ROW] = float(kin_row_idx)
            vol_matrix[i, VolumeCol.FIXED_VOLUME] = -1.0
        elif isinstance(vol, PlenumVolumeConfig):
            vol_matrix[i, VolumeCol.TYPE] = float(VolumeType.PLENUM)
            vol_matrix[i, VolumeCol.KIN_ROW] = -1.0
            vol_matrix[i, VolumeCol.FIXED_VOLUME] = vol.fixed_volume_m3
        elif isinstance(vol, EnvironmentVolumeConfig):
            vol_matrix[i, VolumeCol.TYPE] = float(VolumeType.ENVIRONMENT)
            vol_matrix[i, VolumeCol.KIN_ROW] = -1.0
            vol_matrix[i, VolumeCol.FIXED_VOLUME] = 0.0
            environment_is_fixed[i] = 1
            environment_pressures_pa[i] = float(vol.pressure_Pa)
            environment_temperatures_K[i] = float(vol.temperature_K)
        else:
            raise TypeError(f'Unsupported volume config: {type(vol)!r}')

        if isinstance(vol, EnvironmentVolumeConfig):
            vol_matrix[i, VolumeCol.WALL_ROW] = -1.0
            vol_matrix[i, VolumeCol.COMB_ROW] = -1.0
            vol_matrix[i, VolumeCol.EVAP_ROW] = -1.0
            continue

        if isinstance(vol.wall_heat, WoschniHeatTransferConfig):
            wall_idx = len(wall_rows)
            wall_row = np.zeros((len(WallCol),), dtype=np.float64)
            wall_row[WallCol.MODEL] = float(HeatTransferModel.WOSCHNI)
            wall_row[WallCol.C1] = 0.0 if vol.wall_heat.c1 is None else float(vol.wall_heat.c1)
            wall_row[WallCol.C2] = 0.0 if vol.wall_heat.c2 is None else float(vol.wall_heat.c2)
            wall_row[WallCol.C3] = 0.0 if vol.wall_heat.c3 is None else float(vol.wall_heat.c3)
            wall_row[WallCol.WALL_TEMP] = float(vol.wall_heat.wall_temperature_K)
            wall_row[WallCol.WALL_AREA] = float(vol.wall_heat.wall_area_m2)
            wall_row[WallCol.VARIANT] = float(builder._woschni_variant_enum(vol.wall_heat.variant))
            wall_row[WallCol.DP_MODE] = float(builder._woschni_dp_mode_enum(vol.wall_heat.dp_mode))
            wall_row[WallCol.REF_MODE] = float(builder._woschni_reference_mode_enum(vol.wall_heat.reference_state_mode))
            wall_row[WallCol.PHASE_MODE] = float(builder._woschni_phase_mode_enum(vol.wall_heat.phase_mode))
            wall_row[WallCol.MULTIPLIER] = float(vol.wall_heat.multiplier)
            wall_row[WallCol.CUCM] = float(vol.wall_heat.cucm)
            wall_row[WallCol.SWIRL_NUMBER] = float(vol.wall_heat.swirl_number)
            wall_row[WallCol.IMEP_BAR] = float(vol.wall_heat.imep_bar)
            if isinstance(vol, CylinderVolumeConfig):
                clearance_vol, max_vol = builder._cylinder_reference_volumes(vol)
                wall_row[WallCol.CLEARANCE_VOL] = clearance_vol
                wall_row[WallCol.MAX_VOL] = max_vol
            if isinstance(getattr(vol, "wall_temperature", None), CycleAverageWallTemperatureConfig):
                wall_temp_cfg = vol.wall_temperature
                total_area = 0.0
                weighted_temp = 0.0
                base_state_idx = state_layout.total_size + len(wall_temperature_initials) + len(wall_temperature_average_initials)
                for local_zone_offset, (zone_enum, zone_name, zone_cfg) in enumerate(_wall_temperature_zones(wall_temp_cfg)):
                    zone = int(zone_enum)
                    state_idx = base_state_idx + local_zone_offset
                    wall_temperature_state_index_by_vol[i, zone] = state_idx
                    wall_temperature_params_by_vol[i, zone, WallTemperatureCol.AREA] = float(zone_cfg.area_m2)
                    wall_temperature_params_by_vol[i, zone, WallTemperatureCol.CONDUCTANCE] = float(zone_cfg.lambda_W_per_mK) / float(zone_cfg.wall_thickness_m)
                    wall_temperature_params_by_vol[i, zone, WallTemperatureCol.COOLANT_TEMP] = float(zone_cfg.coolant_temperature_K)
                    wall_temperature_params_by_vol[i, zone, WallTemperatureCol.RELAXATION] = float(wall_temp_cfg.relaxation)
                    wall_temperature_params_by_vol[i, zone, WallTemperatureCol.ENABLED] = 1.0
                    wall_temperature_initials.append((i, str(zone_name), float(zone_cfg.initial_temperature_K)))
                    total_area += float(zone_cfg.area_m2)
                    weighted_temp += float(zone_cfg.area_m2) * float(zone_cfg.initial_temperature_K)
                avg_base_idx = base_state_idx + n_wall_zones
                wall_temperature_average_state_index_by_vol[i, 0] = avg_base_idx
                wall_temperature_average_state_index_by_vol[i, 1] = avg_base_idx + 1
                wall_temperature_average_initials.append((i, "alpha_avg_W_per_m2K", 0.0))
                wall_temperature_average_initials.append((i, "T_alpha_avg_KW_per_m2K", 0.0))
                if total_area > 0.0:
                    wall_row[WallCol.WALL_AREA] = total_area
                    wall_row[WallCol.WALL_TEMP] = weighted_temp / total_area
            wall_rows.append(wall_row.tolist())
            wall_ref_rows.append([0.0, 0.0, 0.0, 0.0, 0.0, -1.0])
            vol_matrix[i, VolumeCol.WALL_ROW] = float(wall_idx)
        elif isinstance(vol.wall_heat, DisabledSubmodelConfig):
            vol_matrix[i, VolumeCol.WALL_ROW] = -1.0
        else:
            raise TypeError('Unsupported wall_heat model')

        if isinstance(vol.combustion, VibeCombustionConfig):
            comb_idx = len(comb_rows)
            q_total_J = _resolve_combustion_total_energy_J(vol.combustion, float(vol.kinematics.stroke_m))
            fuel_mass_cfg = float(getattr(vol.combustion, 'fuel_mass_per_cycle_kg', 0.0) or 0.0)
            lhv_cfg = float(getattr(vol.combustion, 'lhv_J_per_kg', 0.0) or 0.0)
            if fuel_mass_cfg > 0.0 and lhv_cfg > 0.0:
                comb_fuel_mass = fuel_mass_cfg
                comb_lhv = lhv_cfg
            else:
                comb_fuel_mass = 0.0
                comb_lhv = 1.0
            combustion_fuel_mass_by_vol[i] = comb_fuel_mass
            combustion_afr_stoich_by_vol[i] = float(getattr(vol.combustion, 'afr_stoich_kg_air_per_kg_fuel', 14.5) or 14.5)
            comb_rows.append([
                float(CombustionModel.VIBE),
                vol.combustion.start_deg,
                vol.combustion.duration_deg,
                vol.combustion.a,
                vol.combustion.m,
                comb_fuel_mass if comb_fuel_mass > 0.0 else q_total_J,
                comb_lhv if comb_fuel_mass > 0.0 else 1.0,
                float(builder._ref_enum(vol.combustion.angle_reference)),
                float(CombStartMode.ANGLE),
                float(CombDurationMode.ANGLE),
            ])
            vol_matrix[i, VolumeCol.COMB_ROW] = float(comb_idx)
        elif isinstance(vol.combustion, DisabledCombustionConfig):
            vol_matrix[i, VolumeCol.COMB_ROW] = -1.0
        else:
            raise TypeError('Unsupported combustion model')

        if isinstance(vol.evaporation, SimpleEvaporationConfig):
            evap_idx = len(evap_rows)
            evap_rows.append([
                float(EvaporationModel.SIMPLE),
                vol.evaporation.start_deg,
                vol.evaporation.duration_deg,
                vol.evaporation.evaporated_mass_per_cycle_kg,
                vol.evaporation.latent_heat_J_per_kg,
                float(builder._ref_enum(vol.evaporation.angle_reference)),
            ])
            vol_matrix[i, VolumeCol.EVAP_ROW] = float(evap_idx)
        elif isinstance(vol.evaporation, DisabledEvaporationConfig):
            vol_matrix[i, VolumeCol.EVAP_ROW] = -1.0
        else:
            raise TypeError('Unsupported evaporation model')

    kin_matrix = np.asarray(kin_rows, dtype=np.float64) if kin_rows else np.zeros((0, len(KinCol)), dtype=np.float64)
    wall_matrix = np.asarray(wall_rows, dtype=np.float64) if wall_rows else np.zeros((0, len(WallCol)), dtype=np.float64)
    wall_ref_matrix = np.asarray(wall_ref_rows, dtype=np.float64) if wall_ref_rows else np.zeros((0, len(WallRefCol)), dtype=np.float64)
    comb_matrix = np.asarray(comb_rows, dtype=np.float64) if comb_rows else np.zeros((0, len(CombCol)), dtype=np.float64)
    evap_matrix = np.asarray(evap_rows, dtype=np.float64) if evap_rows else np.zeros((0, len(EvapCol)), dtype=np.float64)

    conn_matrix, lift_table, alpha_table, cd_table, connection_names = build_connection_tables(
        builder,
        config=config,
        vol_matrix=vol_matrix,
        kin_matrix=kin_matrix,
        name_to_index=name_to_index,
        allow_valves=True,
        allow_slot_by_angle=True,
    )

    gas_props = build_gas_props(config)
    gas_thermo_model = build_gas_thermo_model(config)
    feature_flags = build_feature_flags(config)
    simulation = build_simulation_options(config, cycle_period_s)
    postprocessing = build_postprocessing_options(config)
    wall_temperature_extra_state_count = len(wall_temperature_initials) + len(wall_temperature_average_initials)
    jac_sparsity = build_rhs_jacobian_sparsity(n_vol, conn_matrix, feature_flags, extra_state_count=wall_temperature_extra_state_count, dense_extra_coupling=bool(wall_temperature_extra_state_count))
    jac_color_groups = greedy_color_columns(jac_sparsity)
    wall_ref_matrix_safe = wall_ref_matrix if wall_ref_matrix.size > 0 else np.zeros((max(wall_matrix.shape[0], 1), len(WallRefCol)), dtype=np.float64)
    if wall_temperature_extra_state_count:
        old_size = y_init.size
        extra_labels = [f"{volume_names[i]}_wall_{zone_name}_temperature_K" for i, zone_name, _temp in wall_temperature_initials]
        extra_labels += [f"{volume_names[i]}_wall_temperature_{avg_name}" for i, avg_name, _value in wall_temperature_average_initials]
        state_layout = state_layout.with_extra_states(extra_labels)
        y_ext = np.zeros(state_layout.total_size, dtype=np.float64)
        y_ext[:old_size] = y_init
        for offset, (_vol_i, _zone_name, temp) in enumerate(wall_temperature_initials):
            y_ext[old_size + offset] = temp
        avg_offset0 = old_size + len(wall_temperature_initials)
        for offset, (_vol_i, _avg_name, value) in enumerate(wall_temperature_average_initials):
            y_ext[avg_offset0 + offset] = value
        y_init = y_ext
    wall_bore_by_vol = np.zeros(n_vol, dtype=np.float64)
    wall_ups_by_vol = np.zeros(n_vol, dtype=np.float64)
    for i in range(n_vol):
        if int(vol_matrix[i, VolumeCol.TYPE]) != VolumeType.CYLINDER:
            continue
        kin_idx = int(vol_matrix[i, VolumeCol.KIN_ROW])
        kin_row = kin_matrix[kin_idx]
        wall_bore_by_vol[i] = kin_row[KinCol.BORE]
        wall_ups_by_vol[i] = 2.0 * kin_row[KinCol.STROKE] * kin_row[KinCol.SPEED_RPM] / 60.0

    for i in range(n_vol):
        if int(environment_is_fixed[i]) == 1 or int(vol_matrix[i, VolumeCol.TYPE]) == VolumeType.ENVIRONMENT:
            continue
        gas_mass_i = float(y_init[int(state_layout.mass_index(i))])
        burned_mass_i = float(y_init[int(state_layout.burned_mass_index(i))])
        unburned_capacity_i = max(gas_mass_i - burned_mass_i, 0.0)
        evap_mass_i = 0.0
        evap_idx_i = int(vol_matrix[i, VolumeCol.EVAP_ROW])
        if evap_idx_i >= 0 and evap_idx_i < int(evap_matrix.shape[0]):
            evap_mass_i = max(float(evap_matrix[evap_idx_i, EvapCol.EVAP_MASS_PER_CYCLE]), 0.0)
        premixed_fuel_vapor_i = 0.0
        if evap_mass_i <= 1.0e-18:
            premixed_fuel_vapor_i = max(float(combustion_fuel_mass_by_vol[i]), 0.0)
        if premixed_fuel_vapor_i > unburned_capacity_i:
            premixed_fuel_vapor_i = unburned_capacity_i
        y_init[int(state_layout.air_mass_index(i))] = max(unburned_capacity_i - premixed_fuel_vapor_i, 0.0)
        y_init[int(state_layout.liquid_fuel_mass_index(i))] = evap_mass_i


    cv_fallback = float(config.gas_properties.cv_J_per_kgK)
    if gas_thermo_model == 'promo':
        for i, vol in enumerate(config.volumes):
            if isinstance(vol, EnvironmentVolumeConfig):
                continue
            m_idx = int(state_layout.mass_index(i))
            u_idx = int(state_layout.energy_index(i))
            air_idx = int(state_layout.air_mass_index(i))
            burned_idx = int(state_layout.burned_mass_index(i))
            mass_i = float(y_init[m_idx])
            air_i = float(y_init[air_idx])
            burned_i = float(y_init[burned_idx])
            fuel_vapor_i = max(mass_i - air_i - burned_i, 0.0)
            temp_i = float(getattr(vol, 'initial_temperature_K', 300.0))
            _cp_i, cv_i, _R_i, _kappa_i = reduced_mixture_properties_from_temperature_quellen(temp_i, air_i, fuel_vapor_i, burned_i)
            y_init[u_idx] = mass_i * max(cv_i, cv_fallback) * temp_i

    return ModelBundle(
        y_init=y_init,
        architecture="classic",
        state_layout=state_layout,
        vol_matrix=vol_matrix,
        kin_matrix=kin_matrix,
        conn_matrix=conn_matrix,
        wall_matrix=wall_matrix,
        wall_ref_matrix=wall_ref_matrix,
        wall_ref_matrix_safe=wall_ref_matrix_safe,
        wall_bore_by_vol=wall_bore_by_vol,
        wall_ups_by_vol=wall_ups_by_vol,
        wall_temperature_enabled=bool(wall_temperature_extra_state_count),
        wall_temperature_state_index_by_vol=wall_temperature_state_index_by_vol,
        wall_temperature_average_state_index_by_vol=wall_temperature_average_state_index_by_vol,
        wall_temperature_params_by_vol=wall_temperature_params_by_vol,
        comb_matrix=comb_matrix,
        evap_matrix=evap_matrix,
        lift_table=lift_table,
        alpha_table=alpha_table,
        cd_table=cd_table,
        gas_props=gas_props,
        gas_thermo_model=gas_thermo_model,
        feature_flags=feature_flags,
        cycle_period_s=cycle_period_s,
        cycle_deg=cycle_deg,
        volume_names=volume_names,
        connection_names=connection_names,
        cylinder_indices=cylinder_indices,
        simulation=simulation,
        postprocessing=postprocessing,
        jac_sparsity=jac_sparsity,
        jac_color_groups=jac_color_groups,
        environment_is_fixed=environment_is_fixed,
        environment_pressures_pa=environment_pressures_pa,
        environment_temperatures_K=environment_temperatures_K,
        combustion_fuel_mass_by_vol=combustion_fuel_mass_by_vol,
        combustion_afr_stoich_by_vol=combustion_afr_stoich_by_vol,
    )
