from __future__ import annotations

import numpy as np

from thermo0d.compute.jacobian import build_rhs_jacobian_sparsity, greedy_color_columns
from thermo0d.config.constants import AngleReference, CombCol, CombDurationMode, CombStartMode, CombustionModel, ConnCol, ConnectionType, CycleType, EvapCol, HeatTransferModel, VolumeCol, VolumeType, WallCol, WallRefCol
from thermo0d.config.models import BounceChamberVolumeConfig, CylinderVolumeConfig, DisabledSubmodelConfig, EnvironmentVolumeConfig, HcciDieselCombustionConfig, PlenumVolumeConfig, VibeCombustionConfig, WoschniHeatTransferConfig
from thermo0d.core.model_bundle import FreePistonModelData, ModelBundle
from thermo0d.model.free_piston.combustion_latch import bootstrap_free_piston_combustion_latch
from thermo0d.core.state_layout import StateLayout
from thermo0d.input.builder_common import (
    assign_state_from_mass_and_temperature,
    build_connection_tables,
    build_environment_buffers,
    build_feature_flags,
    build_gas_props,
    build_gas_thermo_model,
    build_postprocessing_options,
    build_simulation_options,
)
from thermo0d.model.free_piston.geometry import bounce_volume_from_position, cylinder_volume_from_position, free_piston_generalized_initial_state
from thermo0d.physics.quellen_props import reduced_mixture_properties_from_temperature_quellen
from thermo0d.model.free_piston.state_layout import build_free_piston_state_layout
from thermo0d.model.free_piston.thermo import mass_from_pTV, specific_internal_energy_from_temperature


def _initial_cylinder_burned_fraction_0to1(fp, cylinder_vol: CylinderVolumeConfig | None = None) -> float:
    combustion_state = getattr(getattr(fp, "initial_conditions", None), "combustion_state", None)
    if combustion_state is not None:
        if hasattr(combustion_state, "resolved_burned_fraction_0to1"):
            value = float(combustion_state.resolved_burned_fraction_0to1)
        else:
            value = float(getattr(combustion_state, "burned_fraction_0to1", 0.0) or 0.0)
        if getattr(combustion_state, "burned_mass_percent", None) is not None or abs(value) > 1.0e-15 or cylinder_vol is None:
            return min(max(value, 0.0), 1.0)
    if cylinder_vol is None:
        return 0.0
    if hasattr(cylinder_vol, "resolved_initial_burned_fraction_0to1"):
        value = float(cylinder_vol.resolved_initial_burned_fraction_0to1)
    elif getattr(cylinder_vol, "initial_burned_mass_percent", None) is not None:
        value = float(cylinder_vol.initial_burned_mass_percent) / 100.0
    else:
        value = float(getattr(cylinder_vol, "initial_burned_fraction_0to1", 0.0) or 0.0)
    return min(max(value, 0.0), 1.0)


class _ResolvedBounceGeometry:
    def __init__(self, *, name: str, initial_pressure_Pa: float, initial_temperature_K: float, model: str, chamber_diameter_m: float, chamber_length_m: float, compression_ratio: float, chamber_cross_section_m2: float, swept_volume_m3: float, area_m2: float, chamber_min_volume_m3: float, chamber_volume0_m3: float, p0_Pa: float, polytropic_exponent: float) -> None:
        self.name = name
        self.initial_pressure_Pa = initial_pressure_Pa
        self.initial_temperature_K = initial_temperature_K
        self.model = model
        self.chamber_diameter_m = chamber_diameter_m
        self.chamber_length_m = chamber_length_m
        self.compression_ratio = compression_ratio
        self.chamber_cross_section_m2 = chamber_cross_section_m2
        self.swept_volume_m3 = swept_volume_m3
        self.area_m2 = area_m2
        self.chamber_min_volume_m3 = chamber_min_volume_m3
        self.chamber_volume0_m3 = chamber_volume0_m3
        self.p0_Pa = p0_Pa
        self.polytropic_exponent = polytropic_exponent


def _derive_bounce_reference_pressure_Pa(*, initial_pressure_Pa: float, x0_m: float, chamber_volume0_m3: float, area_m2: float, x_min_m: float, x_max_m: float, polytropic_exponent: float) -> float:
    initial_volume_m3 = bounce_volume_from_position(chamber_volume0_m3, area_m2, x0_m, x_min_m, x_max_m)
    ratio = float(chamber_volume0_m3 / max(initial_volume_m3, 1.0e-18))
    return float(initial_pressure_Pa / (ratio ** polytropic_exponent))


def _ensure_bounce_pressure_consistency(*, initial_pressure_Pa: float, x0_m: float, chamber_volume0_m3: float, area_m2: float, x_min_m: float, x_max_m: float, p0_Pa: float, polytropic_exponent: float, context: str) -> float:
    _ = (p0_Pa, context)
    # initial_pressure_Pa at x0_m is the leading start-state definition.
    # p0_Pa is therefore optional metadata only; the effective reference pressure
    # used by the gas spring is derived from the actual configured start state.
    derived_p0_Pa = _derive_bounce_reference_pressure_Pa(
        initial_pressure_Pa=initial_pressure_Pa,
        x0_m=x0_m,
        chamber_volume0_m3=chamber_volume0_m3,
        area_m2=area_m2,
        x_min_m=x_min_m,
        x_max_m=x_max_m,
        polytropic_exponent=polytropic_exponent,
    )
    return float(derived_p0_Pa)


def _resolve_bounce_geometry(fp, input_volumes) -> _ResolvedBounceGeometry:
    nominal_stroke_m = max(float(fp.mechanics.x_max_m) - float(fp.mechanics.x_min_m), 0.0)
    if nominal_stroke_m <= 1.0e-18:
        raise ValueError('free-piston nominal stroke must be > 0 for bounce geometry')

    bounce_volumes = [vol for vol in input_volumes if isinstance(vol, BounceChamberVolumeConfig)]
    if bounce_volumes:
        vol = bounce_volumes[0]
        if vol.chamber_volume0_m3 is not None:
            chamber_volume0_m3 = float(vol.chamber_volume0_m3)
            swept_volume_m3 = float(_fp_piston_area_m2(fp) * nominal_stroke_m)
            if chamber_volume0_m3 <= swept_volume_m3 + 1.0e-18:
                raise ValueError('legacy bounce_chamber chamber_volume0_m3 must be greater than the effective swept volume')
            chamber_min_volume_m3 = float(chamber_volume0_m3 - swept_volume_m3)
            compression_ratio = float(chamber_volume0_m3 / chamber_min_volume_m3)
            chamber_diameter_m = float(vol.chamber_diameter_m) if vol.chamber_diameter_m is not None else _fp_piston_diameter_m(fp)
            chamber_cross_section_m2 = float(0.25 * np.pi * chamber_diameter_m * chamber_diameter_m)
            chamber_length_m = float(swept_volume_m3 / max(chamber_cross_section_m2, 1.0e-18))
        else:
            chamber_diameter_m = float(vol.chamber_diameter_m)
            chamber_length_m = float(vol.chamber_length_m)
            compression_ratio = float(vol.compression_ratio)
            chamber_cross_section_m2 = float(vol.derived_geometric_area_m2)
            swept_volume_m3 = float(vol.derived_swept_volume_m3)
            chamber_min_volume_m3 = float(vol.derived_chamber_min_volume_m3)
            chamber_volume0_m3 = float(vol.derived_chamber_volume0_m3)
        area_m2 = float(swept_volume_m3 / nominal_stroke_m)
        resolved_p0_Pa = _ensure_bounce_pressure_consistency(
            initial_pressure_Pa=float(vol.initial_pressure_Pa),
            x0_m=float(fp.initial_conditions.x0_m),
            chamber_volume0_m3=float(chamber_volume0_m3),
            area_m2=area_m2,
            x_min_m=float(fp.mechanics.x_min_m),
            x_max_m=float(fp.mechanics.x_max_m),
            p0_Pa=None if vol.p0_Pa is None else float(vol.p0_Pa),
            polytropic_exponent=float(vol.polytropic_exponent),
            context=f"bounce_chamber '{vol.name}'",
        )
        return _ResolvedBounceGeometry(
            name=str(vol.name),
            initial_pressure_Pa=float(vol.initial_pressure_Pa),
            initial_temperature_K=float(vol.initial_temperature_K),
            model=str(vol.model),
            chamber_diameter_m=chamber_diameter_m,
            chamber_length_m=chamber_length_m,
            compression_ratio=compression_ratio,
            chamber_cross_section_m2=chamber_cross_section_m2,
            swept_volume_m3=swept_volume_m3,
            area_m2=area_m2,
            chamber_min_volume_m3=float(chamber_min_volume_m3),
            chamber_volume0_m3=float(chamber_volume0_m3),
            p0_Pa=float(resolved_p0_Pa),
            polytropic_exponent=float(vol.polytropic_exponent),
        )

    if fp.bounce is None:
        raise ValueError('free_piston requires either a bounce_chamber volume or legacy free_piston.bounce settings')

    chamber_diameter_m = _fp_bounce_chamber_diameter_m(fp)
    chamber_cross_section_m2 = _fp_bounce_chamber_cross_section_m2(fp)
    swept_volume_m3 = _fp_bounce_swept_volume_m3(fp)
    chamber_min_volume_m3 = _fp_bounce_chamber_min_volume_m3(fp)
    chamber_volume0_m3 = _fp_bounce_chamber_volume0_m3(fp)
    compression_ratio = _fp_bounce_compression_ratio(fp)
    chamber_length_m = _fp_bounce_chamber_length_m(fp)
    area_m2 = _fp_bounce_area_m2(fp)
    bounce_init = fp.initial_conditions.bounce
    if bounce_init is None:
        raise ValueError('legacy free_piston.bounce requires free_piston.initial_conditions.bounce')
    resolved_p0_Pa = _ensure_bounce_pressure_consistency(
        initial_pressure_Pa=float(bounce_init.pressure_Pa),
        x0_m=float(fp.initial_conditions.x0_m),
        chamber_volume0_m3=chamber_volume0_m3,
        area_m2=area_m2,
        x_min_m=float(fp.mechanics.x_min_m),
        x_max_m=float(fp.mechanics.x_max_m),
        p0_Pa=None if fp.bounce.p0_Pa is None else float(fp.bounce.p0_Pa),
        polytropic_exponent=float(fp.bounce.polytropic_exponent),
        context='free_piston.bounce',
    )
    return _ResolvedBounceGeometry(
        name='bounce',
        initial_pressure_Pa=float(bounce_init.pressure_Pa),
        initial_temperature_K=float(bounce_init.temperature_K),
        model=str(fp.bounce.model),
        chamber_diameter_m=chamber_diameter_m,
        chamber_length_m=chamber_length_m,
        compression_ratio=compression_ratio,
        chamber_cross_section_m2=chamber_cross_section_m2,
        swept_volume_m3=swept_volume_m3,
        area_m2=area_m2,
        chamber_min_volume_m3=chamber_min_volume_m3,
        chamber_volume0_m3=chamber_volume0_m3,
        p0_Pa=float(resolved_p0_Pa),
        polytropic_exponent=float(fp.bounce.polytropic_exponent),
    )


def _fp_piston_area_m2(fp) -> float:
    return float(fp.mechanics.derived_piston_area_m2)


def _fp_clearance_volume_m3(fp) -> float:
    return float(fp.mechanics.derived_clearance_volume_m3)


def _fp_piston_diameter_m(fp) -> float:
    return float(fp.mechanics.derived_piston_diameter_m)


def _fp_compression_ratio(fp) -> float:
    return float(fp.mechanics.derived_compression_ratio)


def _fp_kinematics_type(fp) -> str:
    return str(getattr(fp.mechanics, 'kinematics_type', 'linear') or 'linear')


def _fp_rotary_angle_min_rad(fp) -> float:
    return float(np.deg2rad(float(getattr(fp.mechanics, 'angle_min_deg', 0.0) or 0.0)))


def _fp_rotary_angle_max_rad(fp) -> float:
    return float(np.deg2rad(float(getattr(fp.mechanics, 'angle_max_deg', 0.0) or 0.0)))


def _fp_rotary_effective_radius_m(fp) -> float:
    if _fp_kinematics_type(fp) == 'oscillating_rotary':
        return float(getattr(fp.mechanics, 'effective_radius_m'))
    return 1.0


def _fp_rotary_inertia_kg_m2(fp) -> float:
    if _fp_kinematics_type(fp) == 'oscillating_rotary':
        return float(getattr(fp.mechanics, 'rotary_inertia_kg_m2'))
    return float(fp.mechanics.moving_mass_kg)


def _fp_bounce_chamber_diameter_m(fp) -> float:
    if fp.bounce.chamber_diameter_m is not None:
        return float(fp.bounce.chamber_diameter_m)
    return _fp_piston_diameter_m(fp)


def _fp_bounce_chamber_cross_section_m2(fp) -> float:
    diameter_m = _fp_bounce_chamber_diameter_m(fp)
    return float(0.25 * np.pi * diameter_m * diameter_m)


def _fp_bounce_swept_volume_m3(fp) -> float:
    if fp.bounce.chamber_volume0_m3 is not None:
        return float(_fp_piston_area_m2(fp) * max(float(fp.mechanics.x_max_m) - float(fp.mechanics.x_min_m), 0.0))
    return float(fp.bounce.derived_swept_volume_m3)


def _fp_bounce_compression_ratio(fp) -> float:
    if fp.bounce.compression_ratio is not None:
        return float(fp.bounce.compression_ratio)
    vmax = float(fp.bounce.chamber_volume0_m3)
    swept = _fp_bounce_swept_volume_m3(fp)
    if vmax <= swept + 1.0e-18:
        raise ValueError('legacy free-piston bounce geometry invalid: chamber_volume0_m3 must be greater than the effective swept volume')
    return float(vmax / (vmax - swept))


def _fp_bounce_chamber_length_m(fp) -> float:
    if fp.bounce.chamber_length_m is not None:
        return float(fp.bounce.chamber_length_m)
    area_m2 = _fp_bounce_chamber_cross_section_m2(fp)
    return float(_fp_bounce_swept_volume_m3(fp) / max(area_m2, 1.0e-18))


def _fp_bounce_chamber_min_volume_m3(fp) -> float:
    if fp.bounce.chamber_volume0_m3 is not None:
        return float(fp.bounce.chamber_volume0_m3) - _fp_bounce_swept_volume_m3(fp)
    return float(fp.bounce.derived_chamber_min_volume_m3)


def _fp_bounce_chamber_volume0_m3(fp) -> float:
    if fp.bounce.chamber_volume0_m3 is not None:
        return float(fp.bounce.chamber_volume0_m3)
    return float(fp.bounce.derived_chamber_volume0_m3)


def _fp_bounce_area_m2(fp) -> float:
    nominal_stroke_m = max(float(fp.mechanics.x_max_m) - float(fp.mechanics.x_min_m), 0.0)
    if nominal_stroke_m <= 1.0e-18:
        raise ValueError('free-piston nominal stroke must be > 0 for bounce geometry')
    return float(_fp_bounce_swept_volume_m3(fp) / nominal_stroke_m)


def _free_piston_cylinder_initial_mass_energy(
    *,
    fp,
    cylinder_vol: CylinderVolumeConfig | None,
    volume_m3: float,
    gas_constant_J_per_kgK: float,
    cv_J_per_kgK: float,
) -> tuple[float, float, float, float]:
    if cylinder_vol is not None:
        temperature_K = float(cylinder_vol.initial_temperature_K)
        if cylinder_vol.initial_pressure_Pa is not None:
            pressure_Pa = float(cylinder_vol.initial_pressure_Pa)
            mass_kg = mass_from_pTV(
                pressure_Pa=pressure_Pa,
                temperature_K=temperature_K,
                volume_m3=float(volume_m3),
                gas_constant_J_per_kgK=float(gas_constant_J_per_kgK),
            )
        elif cylinder_vol.initial_mass_kg is not None:
            mass_kg = float(cylinder_vol.initial_mass_kg)
            pressure_Pa = float(mass_kg * float(gas_constant_J_per_kgK) * temperature_K / max(float(volume_m3), 1.0e-18))
        else:
            raise ValueError('free-piston cylinder volume requires initial_pressure_Pa or initial_mass_kg')
    else:
        fp_cylinder = getattr(fp.initial_conditions, 'cylinder', None)
        if fp_cylinder is None:
            raise ValueError(
                'free_piston architecture requires a cylinder volume with initial_pressure_Pa/initial_mass_kg '
                'and initial_temperature_K in preprocessing.volumes'
            )
        pressure_Pa = float(fp_cylinder.pressure_Pa)
        temperature_K = float(fp_cylinder.temperature_K)
        mass_kg = mass_from_pTV(
            pressure_Pa=pressure_Pa,
            temperature_K=temperature_K,
            volume_m3=float(volume_m3),
            gas_constant_J_per_kgK=float(gas_constant_J_per_kgK),
        )

    internal_energy_J = float(
        mass_kg
        * specific_internal_energy_from_temperature(
            temperature_K=temperature_K,
            cv_J_per_kgK=float(cv_J_per_kgK),
        )
    )
    return float(pressure_Pa), float(temperature_K), float(mass_kg), float(internal_energy_J)


def _build_free_piston_wall_matrices(builder, cylinder_cfg_for_submodels: CylinderVolumeConfig | None, fp) -> tuple[np.ndarray, np.ndarray, np.ndarray, int]:
    if cylinder_cfg_for_submodels is None:
        return (
            np.zeros((0, len(WallCol)), dtype=np.float64),
            np.zeros((0, len(WallRefCol)), dtype=np.float64),
            np.zeros((1, len(WallRefCol)), dtype=np.float64),
            -1,
        )

    wall_cfg = cylinder_cfg_for_submodels.wall_heat
    if isinstance(wall_cfg, DisabledSubmodelConfig):
        return (
            np.zeros((0, len(WallCol)), dtype=np.float64),
            np.zeros((0, len(WallRefCol)), dtype=np.float64),
            np.zeros((1, len(WallRefCol)), dtype=np.float64),
            -1,
        )
    if not isinstance(wall_cfg, WoschniHeatTransferConfig):
        raise TypeError('Unsupported wall_heat model for free_piston cylinder')

    nominal_stroke_m = max(float(fp.mechanics.x_max_m) - float(fp.mechanics.x_min_m), 0.0)
    max_vol = float(_fp_clearance_volume_m3(fp) + _fp_piston_area_m2(fp) * nominal_stroke_m)

    wall_row = np.zeros((len(WallCol),), dtype=np.float64)
    wall_row[WallCol.MODEL] = float(HeatTransferModel.WOSCHNI)
    wall_row[WallCol.C1] = 0.0 if wall_cfg.c1 is None else float(wall_cfg.c1)
    wall_row[WallCol.C2] = 0.0 if wall_cfg.c2 is None else float(wall_cfg.c2)
    wall_row[WallCol.C3] = 0.0 if wall_cfg.c3 is None else float(wall_cfg.c3)
    wall_row[WallCol.WALL_TEMP] = float(wall_cfg.wall_temperature_K)
    wall_row[WallCol.WALL_AREA] = float(wall_cfg.wall_area_m2)
    wall_row[WallCol.VARIANT] = float(builder._woschni_variant_enum(wall_cfg.variant))
    wall_row[WallCol.DP_MODE] = float(builder._woschni_dp_mode_enum(wall_cfg.dp_mode))
    wall_row[WallCol.REF_MODE] = float(builder._woschni_reference_mode_enum(wall_cfg.reference_state_mode))
    wall_row[WallCol.PHASE_MODE] = float(builder._woschni_phase_mode_enum(wall_cfg.phase_mode))
    wall_row[WallCol.MULTIPLIER] = float(wall_cfg.multiplier)
    wall_row[WallCol.CUCM] = float(wall_cfg.cucm)
    wall_row[WallCol.SWIRL_NUMBER] = float(wall_cfg.swirl_number)
    wall_row[WallCol.IMEP_BAR] = float(wall_cfg.imep_bar)
    wall_row[WallCol.CLEARANCE_VOL] = float(_fp_clearance_volume_m3(fp))
    wall_row[WallCol.MAX_VOL] = max_vol

    wall_matrix = wall_row.reshape(1, -1)
    wall_ref_matrix = np.asarray([[0.0, 0.0, 0.0, 0.0, 0.0, -1.0]], dtype=np.float64)
    wall_ref_matrix_safe = wall_ref_matrix.copy()
    return wall_matrix, wall_ref_matrix, wall_ref_matrix_safe, 0


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




def _resolved_combustion_duration_mode_name(combustion_cfg) -> str:
    duration_mode = getattr(combustion_cfg, 'duration_mode', None)
    if duration_mode is not None:
        return str(duration_mode).strip().lower()
    if getattr(combustion_cfg, 'duration_s', None) is not None or getattr(combustion_cfg, 'duration_ms', None) is not None:
        return 'time'
    if getattr(combustion_cfg, 'duration_hub_m', None) is not None and str(getattr(combustion_cfg, 'start_mode', 'angle') or 'angle').strip().lower() == 'compression_hub':
        return 'compression_hub'
    return 'angle'


def _resolve_combustion_timing_for_free_piston(combustion_cfg, nominal_stroke_m: float, cycle_deg: float) -> tuple[float, float, AngleReference, CombStartMode, CombDurationMode]:
    start_mode = str(getattr(combustion_cfg, 'start_mode', 'angle') or 'angle').strip().lower()
    if start_mode == 'compression_hub':
        if nominal_stroke_m <= 1.0e-18:
            raise ValueError('free-piston nominal stroke must be > 0 for compression_hub combustion start mode')
        start_hub_m = float(combustion_cfg.start_hub_m)
        if start_hub_m > nominal_stroke_m + 1.0e-12:
            raise ValueError('start_hub_m must be <= free-piston nominal stroke')
        half_cycle_deg = 0.5 * float(cycle_deg)
        start_value = half_cycle_deg + half_cycle_deg * (start_hub_m / nominal_stroke_m)
        ref_type = AngleReference.COMPRESSION_TDC
        start_mode_enum = CombStartMode.COMPRESSION_HUB
    elif start_mode == 'hign_position':
        start_value = float(combustion_cfg.hign_m) if getattr(combustion_cfg, 'hign_m', None) is not None else float(combustion_cfg.hign_mm) * 1.0e-3
        if start_value <= 0.0:
            raise ValueError('hign_m/hign_mm must resolve to > 0 for hign_position combustion start mode')
        if nominal_stroke_m > 1.0e-18 and start_value > nominal_stroke_m + 1.0e-12:
            raise ValueError('hign_m/hign_mm must be <= free-piston nominal stroke')
        ref_type = AngleReference.COMPRESSION_TDC
        start_mode_enum = CombStartMode.HIGN_POSITION
    else:
        start_value = float(combustion_cfg.start_deg)
        start_mode_enum = CombStartMode.ANGLE
        ref_name = str(getattr(combustion_cfg, 'angle_reference', 'compression_tdc') or 'compression_tdc').strip().lower()
        if ref_name == 'gas_exchange_tdc':
            ref_type = AngleReference.GAS_EXCHANGE_TDC
        elif ref_name == 'absolute':
            ref_type = AngleReference.ABSOLUTE
        else:
            ref_type = AngleReference.COMPRESSION_TDC

    duration_mode = _resolved_combustion_duration_mode_name(combustion_cfg)
    if duration_mode == 'compression_hub':
        if nominal_stroke_m <= 1.0e-18:
            raise ValueError('free-piston nominal stroke must be > 0 for compression_hub combustion duration mode')
        duration_hub_m = float(combustion_cfg.duration_hub_m)
        duration_value = 0.5 * float(cycle_deg) * (duration_hub_m / nominal_stroke_m)
        duration_mode_enum = CombDurationMode.COMPRESSION_HUB
    elif duration_mode == 'time':
        duration_value = float(combustion_cfg.duration_s) if getattr(combustion_cfg, 'duration_s', None) is not None else float(combustion_cfg.duration_ms) * 1.0e-3
        duration_mode_enum = CombDurationMode.TIME
    else:
        duration_value = float(combustion_cfg.duration_deg)
        duration_mode_enum = CombDurationMode.ANGLE
    return float(start_value), float(duration_value), ref_type, start_mode_enum, duration_mode_enum

def build_free_piston_bundle(builder) -> ModelBundle:
    config = builder.config
    if config.free_piston is None:
        raise ValueError("modeling.architecture='free_piston' requires a top-level free_piston section")

    fp = config.free_piston
    input_volumes = list(config.volumes)
    bounce_geom = _resolve_bounce_geometry(fp, input_volumes)
    stateful_bounce_volumes = [vol for vol in input_volumes if isinstance(vol, BounceChamberVolumeConfig) and str(vol.model) == 'gas_exchange']
    build_input_volumes = [
        vol for vol in input_volumes
        if (not isinstance(vol, BounceChamberVolumeConfig)) or (str(vol.model) == 'gas_exchange')
    ]
    placeholder_cylinders = [vol for vol in build_input_volumes if isinstance(vol, CylinderVolumeConfig)]
    cylinder_name = placeholder_cylinders[0].name if placeholder_cylinders else 'cylinder'
    synthetic_cylinder = None
    if not placeholder_cylinders:
        synthetic_cylinder = object()
        volumes_for_build = [synthetic_cylinder]
        volume_names_input = [cylinder_name]
    else:
        volumes_for_build = build_input_volumes
        volume_names_input = [vol.name for vol in build_input_volumes]
    n_vol = len(volumes_for_build)
    explicit_cylinders = [vol for vol in volumes_for_build if isinstance(vol, CylinderVolumeConfig)]
    explicit_bounces = [vol for vol in volumes_for_build if isinstance(vol, BounceChamberVolumeConfig)]
    mechanical_dofs = 1
    cycle_type = builder._cycle_enum(config.engine.cycle_type)
    cycle_deg = 360.0 if cycle_type == CycleType.TWO_STROKE else 720.0
    cycle_period_s = cycle_deg / (6.0 * config.engine.speed_rpm)

    bounce_volume_max_m3 = bounce_geom.chamber_volume0_m3
    bounce_volume_min_m3 = bounce_geom.chamber_min_volume_m3
    if bounce_volume_min_m3 <= 0.0:
        raise ValueError(
            'free-piston bounce geometry invalid: Vmin at OT must be > 0 when derived from bounce swept volume and compression ratio'
        )
    if bounce_volume_max_m3 <= bounce_volume_min_m3:
        raise ValueError(
            'free-piston bounce geometry invalid: Vmax at UT must be greater than Vmin at OT'
        )

    vol_matrix = np.full((n_vol, len(VolumeCol)), -1.0, dtype=np.float64)
    state_layout = build_free_piston_state_layout(n_vol, mechanical_dofs=mechanical_dofs)
    y_init = np.zeros(state_layout.total_size, dtype=np.float64)
    volume_mechanical_dof = np.full(n_vol, -1, dtype=np.int64)
    volume_mechanical_sign = np.zeros(n_vol, dtype=np.float64)
    volume_names: list[str] = []
    name_to_index: dict[str, int] = {}
    cylinder_indices: list[int] = []
    environment_is_fixed, environment_pressures_pa, environment_temperatures_K = build_environment_buffers(n_vol)
    combustion_fuel_mass_by_vol = np.zeros(n_vol, dtype=np.float64)
    combustion_afr_stoich_by_vol = np.full(n_vol, 14.5, dtype=np.float64)
    combustion_lambda_target_by_vol = np.zeros(n_vol, dtype=np.float64)
    combustion_efficiency_by_vol = np.ones(n_vol, dtype=np.float64)
    combustion_lhv_by_vol = np.zeros(n_vol, dtype=np.float64)
    combustion_fueling_mode_by_vol = np.zeros(n_vol, dtype=np.int64)
    combustion_slot_open_threshold_by_vol_m2 = np.full(n_vol, 1.0e-7, dtype=np.float64)
    combustion_slot_closed_threshold_by_vol_m2 = np.full(n_vol, 1.0e-9, dtype=np.float64)
    combustion_compression_velocity_threshold_by_vol_m_per_s = np.full(n_vol, 0.02, dtype=np.float64)
    injector_duration_by_vol_s = np.zeros(n_vol, dtype=np.float64)
    hcci_enabled_by_vol = np.zeros(n_vol, dtype=np.int64)
    hcci_tau_A_by_vol_s = np.zeros(n_vol, dtype=np.float64)
    hcci_pressure_exponent_by_vol = np.zeros(n_vol, dtype=np.float64)
    hcci_activation_temperature_by_vol_K = np.zeros(n_vol, dtype=np.float64)
    hcci_reference_pressure_by_vol_Pa = np.zeros(n_vol, dtype=np.float64)
    hcci_reference_lambda_by_vol = np.ones(n_vol, dtype=np.float64)
    hcci_lambda_slowdown_exponent_by_vol = np.zeros(n_vol, dtype=np.float64)
    hcci_residual_slowdown_factor_by_vol = np.ones(n_vol, dtype=np.float64)
    hcci_start_temperature_min_by_vol_K = np.zeros(n_vol, dtype=np.float64)
    hcci_start_pressure_min_by_vol_Pa = np.zeros(n_vol, dtype=np.float64)
    hcci_max_ignition_delay_by_vol_s = np.zeros(n_vol, dtype=np.float64)

    cylinder_cfg_for_submodels: CylinderVolumeConfig | None = None
    cylinder_cfg_by_index: dict[int, CylinderVolumeConfig] = {}
    cyl_idx: int | None = None
    cylinder_count = 0
    bounce_count = 0
    initial_cylinder_pressure_Pa: float | None = None
    initial_cylinder_temperature_K: float | None = None
    initial_cylinder_volume_m3: float | None = None
    initial_cylinder_mass_kg: float | None = None
    initial_cylinder_internal_energy_J: float | None = None

    for i, vol in enumerate(volumes_for_build):
        vol_name = volume_names_input[i]
        volume_names.append(vol_name)
        name_to_index[vol_name] = i
        m_idx = state_layout.mass_index(i)
        u_idx = state_layout.energy_index(i)

        if synthetic_cylinder is not None and vol is synthetic_cylinder:
            if cyl_idx is not None:
                raise ValueError('free_piston architecture currently supports exactly one cylinder volume')
            cyl_idx = i
            cylinder_indices.append(i)
            volume_mechanical_dof[i] = 0
            volume_mechanical_sign[i] = 1.0
            vol_matrix[i, VolumeCol.TYPE] = float(VolumeType.CYLINDER)
            vol_matrix[i, VolumeCol.KIN_ROW] = -1.0
            vol_matrix[i, VolumeCol.FIXED_VOLUME] = -1.0

            initial_cylinder_volume_m3 = cylinder_volume_from_position(
                clearance_volume_m3=_fp_clearance_volume_m3(fp),
                piston_area_m2=_fp_piston_area_m2(fp),
                x_m=float(fp.initial_conditions.x0_m),
                x_min_m=float(fp.mechanics.x_min_m),
                x_max_m=float(fp.mechanics.x_max_m),
            )
            initial_cylinder_pressure_Pa, initial_cylinder_temperature_K, initial_cylinder_mass_kg, initial_cylinder_internal_energy_J = (
                _free_piston_cylinder_initial_mass_energy(
                    fp=fp,
                    cylinder_vol=None,
                    volume_m3=float(initial_cylinder_volume_m3),
                    gas_constant_J_per_kgK=float(config.gas_properties.R_J_per_kgK),
                    cv_J_per_kgK=float(config.gas_properties.cv_J_per_kgK),
                )
            )
            y_init[m_idx] = initial_cylinder_mass_kg
            y_init[u_idx] = initial_cylinder_internal_energy_J
            initial_burned_mass_kg = initial_cylinder_mass_kg * _initial_cylinder_burned_fraction_0to1(fp, synthetic_cylinder)
            y_init[state_layout.burned_mass_index(i)] = initial_burned_mass_kg
            y_init[state_layout.residual_mass_index(i)] = initial_burned_mass_kg
            cylinder_cfg_for_submodels = placeholder_cylinders[0] if placeholder_cylinders else None
        elif isinstance(vol, CylinderVolumeConfig):
            if cyl_idx is None:
                cyl_idx = i
            cylinder_indices.append(i)
            cylinder_count += 1
            motion_sign = 1.0 if cylinder_count == 1 else -1.0
            volume_mechanical_dof[i] = 0
            volume_mechanical_sign[i] = motion_sign
            vol_matrix[i, VolumeCol.TYPE] = float(VolumeType.CYLINDER)
            vol_matrix[i, VolumeCol.KIN_ROW] = -1.0
            vol_matrix[i, VolumeCol.FIXED_VOLUME] = -1.0
            x_init_i = float(fp.initial_conditions.x0_m) if motion_sign > 0.0 else float(fp.mechanics.x_min_m) + float(fp.mechanics.x_max_m) - float(fp.initial_conditions.x0_m)

            initial_cylinder_volume_m3 = cylinder_volume_from_position(
                clearance_volume_m3=_fp_clearance_volume_m3(fp),
                piston_area_m2=_fp_piston_area_m2(fp),
                x_m=x_init_i,
                x_min_m=float(fp.mechanics.x_min_m),
                x_max_m=float(fp.mechanics.x_max_m),
            )
            initial_cylinder_pressure_Pa, initial_cylinder_temperature_K, initial_cylinder_mass_kg, initial_cylinder_internal_energy_J = (
                _free_piston_cylinder_initial_mass_energy(
                    fp=fp,
                    cylinder_vol=vol,
                    volume_m3=float(initial_cylinder_volume_m3),
                    gas_constant_J_per_kgK=float(config.gas_properties.R_J_per_kgK),
                    cv_J_per_kgK=float(config.gas_properties.cv_J_per_kgK),
                )
            )
            y_init[m_idx] = initial_cylinder_mass_kg
            y_init[u_idx] = initial_cylinder_internal_energy_J
            initial_burned_mass_kg = initial_cylinder_mass_kg * _initial_cylinder_burned_fraction_0to1(fp, vol)
            y_init[state_layout.burned_mass_index(i)] = initial_burned_mass_kg
            y_init[state_layout.residual_mass_index(i)] = initial_burned_mass_kg
            if cylinder_cfg_for_submodels is None:
                cylinder_cfg_for_submodels = vol
            cylinder_cfg_by_index[i] = vol
        elif isinstance(vol, PlenumVolumeConfig):
            vol_matrix[i, VolumeCol.TYPE] = float(VolumeType.PLENUM)
            vol_matrix[i, VolumeCol.KIN_ROW] = -1.0
            vol_matrix[i, VolumeCol.FIXED_VOLUME] = vol.fixed_volume_m3
            initial_mass_kg = builder._initial_mass_kg(vol)
            assign_state_from_mass_and_temperature(
                y_init,
                mass_index=m_idx,
                energy_index=u_idx,
                mass_kg=initial_mass_kg,
                temperature_K=vol.initial_temperature_K,
                cv_J_per_kgK=config.gas_properties.cv_J_per_kgK,
            )
            initial_burned_mass_kg = initial_mass_kg * builder._initial_burned_fraction_0to1(vol)
            y_init[state_layout.burned_mass_index(i)] = initial_burned_mass_kg
            y_init[state_layout.residual_mass_index(i)] = initial_burned_mass_kg
        elif isinstance(vol, BounceChamberVolumeConfig):
            bounce_count += 1
            motion_sign = 1.0 if bounce_count == 1 else -1.0
            volume_mechanical_dof[i] = 0
            volume_mechanical_sign[i] = motion_sign
            vol_matrix[i, VolumeCol.TYPE] = float(VolumeType.BOUNCE_CHAMBER)
            vol_matrix[i, VolumeCol.KIN_ROW] = -1.0
            vol_matrix[i, VolumeCol.FIXED_VOLUME] = -1.0
            x_init_i = float(fp.initial_conditions.x0_m) if motion_sign > 0.0 else float(fp.mechanics.x_min_m) + float(fp.mechanics.x_max_m) - float(fp.initial_conditions.x0_m)
            initial_bounce_volume_m3 = bounce_volume_from_position(
                bounce_geom.chamber_volume0_m3,
                bounce_geom.area_m2,
                x_init_i,
                float(fp.mechanics.x_min_m),
                float(fp.mechanics.x_max_m),
            )
            initial_bounce_mass_kg = mass_from_pTV(
                pressure_Pa=float(vol.initial_pressure_Pa),
                temperature_K=float(vol.initial_temperature_K),
                volume_m3=float(initial_bounce_volume_m3),
                gas_constant_J_per_kgK=float(config.gas_properties.R_J_per_kgK),
            )
            initial_bounce_internal_energy_J = float(
                initial_bounce_mass_kg
                * specific_internal_energy_from_temperature(
                    temperature_K=float(vol.initial_temperature_K),
                    cv_J_per_kgK=float(config.gas_properties.cv_J_per_kgK),
                )
            )
            y_init[m_idx] = initial_bounce_mass_kg
            y_init[u_idx] = initial_bounce_internal_energy_J
            initial_burned_mass_kg = initial_bounce_mass_kg * builder._initial_burned_fraction_0to1(vol)
            y_init[state_layout.burned_mass_index(i)] = initial_burned_mass_kg
            y_init[state_layout.residual_mass_index(i)] = initial_burned_mass_kg
        elif isinstance(vol, EnvironmentVolumeConfig):
            vol_matrix[i, VolumeCol.TYPE] = float(VolumeType.ENVIRONMENT)
            vol_matrix[i, VolumeCol.KIN_ROW] = -1.0
            vol_matrix[i, VolumeCol.FIXED_VOLUME] = 0.0
            environment_is_fixed[i] = 1
            environment_pressures_pa[i] = float(vol.pressure_Pa)
            environment_temperatures_K[i] = float(vol.temperature_K)
            y_init[m_idx] = 0.0
            y_init[u_idx] = 0.0
            y_init[state_layout.burned_mass_index(i)] = 0.0
            y_init[state_layout.residual_mass_index(i)] = 0.0
        else:
            raise TypeError(f'Unsupported volume config: {type(vol)!r}')

        vol_matrix[i, VolumeCol.WALL_ROW] = -1.0
        vol_matrix[i, VolumeCol.COMB_ROW] = -1.0
        vol_matrix[i, VolumeCol.EVAP_ROW] = -1.0

    if (
        cyl_idx is None
        or initial_cylinder_pressure_Pa is None
        or initial_cylinder_temperature_K is None
        or initial_cylinder_volume_m3 is None
        or initial_cylinder_mass_kg is None
        or initial_cylinder_internal_energy_J is None
    ):
        raise ValueError('free_piston architecture requires at least one cylinder volume')

    x_idx, v_idx = state_layout.free_piston_indices()
    mechanical_x_indices = np.array([state_layout.free_piston_indices_for_dof(i)[0] for i in range(mechanical_dofs)], dtype=np.int64)
    mechanical_v_indices = np.array([state_layout.free_piston_indices_for_dof(i)[1] for i in range(mechanical_dofs)], dtype=np.int64)
    q0, qv0 = free_piston_generalized_initial_state(
        float(fp.initial_conditions.x0_m),
        float(fp.initial_conditions.v0_m_per_s),
        kinematics_type=_fp_kinematics_type(fp),
        x_min_m=float(fp.mechanics.x_min_m),
        angle_min_rad=_fp_rotary_angle_min_rad(fp),
        effective_radius_m=_fp_rotary_effective_radius_m(fp),
    )
    for dof in range(mechanical_dofs):
        y_init[int(mechanical_x_indices[dof])] = float(q0)
        y_init[int(mechanical_v_indices[dof])] = float(qv0)

    kin_matrix = np.zeros((0, 8), dtype=np.float64)
    wall_rows: list[np.ndarray] = []
    wall_ref_rows: list[np.ndarray] = []
    wall_ref_safe_rows: list[np.ndarray] = []
    for cyl_i in cylinder_indices:
        cyl_cfg_i = cylinder_cfg_by_index.get(int(cyl_i), cylinder_cfg_for_submodels)
        wall_matrix_i, wall_ref_matrix_i, wall_ref_matrix_safe_i, wall_idx_i = _build_free_piston_wall_matrices(
            builder,
            cyl_cfg_i,
            fp,
        )
        if wall_idx_i >= 0 and wall_matrix_i.shape[0] > 0:
            vol_matrix[int(cyl_i), VolumeCol.WALL_ROW] = float(len(wall_rows))
            wall_rows.append(np.asarray(wall_matrix_i[wall_idx_i], dtype=np.float64))
            wall_ref_rows.append(np.asarray(wall_ref_matrix_i[0], dtype=np.float64))
            wall_ref_safe_rows.append(np.asarray(wall_ref_matrix_safe_i[0], dtype=np.float64))
    wall_matrix = np.asarray(wall_rows, dtype=np.float64) if wall_rows else np.zeros((0, len(WallCol)), dtype=np.float64)
    wall_ref_matrix = np.asarray(wall_ref_rows, dtype=np.float64) if wall_ref_rows else np.zeros((0, len(WallRefCol)), dtype=np.float64)
    wall_ref_matrix_safe = np.asarray(wall_ref_safe_rows, dtype=np.float64) if wall_ref_safe_rows else np.zeros((1, len(WallRefCol)), dtype=np.float64)
    comb_matrix = np.zeros((0, len(CombCol)), dtype=np.float64)
    comb_rows: list[np.ndarray] = []
    nominal_stroke_m = float(fp.mechanics.x_max_m) - float(fp.mechanics.x_min_m)
    for cyl_i in cylinder_indices:
        cyl_cfg_i = cylinder_cfg_by_index.get(int(cyl_i), cylinder_cfg_for_submodels)
        if cyl_cfg_i is None or not isinstance(cyl_cfg_i.combustion, (VibeCombustionConfig, HcciDieselCombustionConfig)):
            continue
        combustion_cfg_local = cyl_cfg_i.combustion
        is_hcci_diesel = isinstance(combustion_cfg_local, HcciDieselCombustionConfig)
        if str(getattr(combustion_cfg_local, 'fueling_mode', 'fixed_energy')) in ('lambda_from_cylinder_mass_at_slot_close', 'lambda_from_cylinder_air_at_slot_close_vapor_injector'):
            q_total_J = 0.0
            comb_fuel_mass = 0.0
            comb_lhv = 1.0
        else:
            q_total_J = _resolve_combustion_total_energy_J(combustion_cfg_local, nominal_stroke_m)
            fuel_mass_cfg = float(getattr(combustion_cfg_local, 'fuel_mass_per_cycle_kg', 0.0) or 0.0)
            lhv_cfg = float(getattr(combustion_cfg_local, 'lhv_J_per_kg', 0.0) or 0.0)
            if fuel_mass_cfg > 0.0 and lhv_cfg > 0.0:
                comb_fuel_mass = fuel_mass_cfg
                comb_lhv = lhv_cfg
            else:
                comb_fuel_mass = 0.0
                comb_lhv = 1.0
        combustion_fuel_mass_by_vol[int(cyl_i)] = comb_fuel_mass
        combustion_afr_stoich_by_vol[int(cyl_i)] = float(getattr(combustion_cfg_local, 'afr_stoich_kg_air_per_kg_fuel', 14.5) or 14.5)
        combustion_lambda_target_by_vol[int(cyl_i)] = float(getattr(combustion_cfg_local, 'lambda_target', 0.0) or 0.0)
        combustion_efficiency_by_vol[int(cyl_i)] = float(getattr(combustion_cfg_local, 'combustion_efficiency_0to1', 1.0) or 1.0)
        combustion_lhv_by_vol[int(cyl_i)] = float(getattr(combustion_cfg_local, 'lhv_J_per_kg', 0.0) or 0.0)
        fueling_mode_name = str(getattr(combustion_cfg_local, 'fueling_mode', 'fixed_energy') or 'fixed_energy')
        if fueling_mode_name == 'lambda_from_cylinder_mass_at_slot_close':
            combustion_fueling_mode_by_vol[int(cyl_i)] = 1
        elif fueling_mode_name == 'lambda_from_cylinder_air_at_slot_close_vapor_injector':
            combustion_fueling_mode_by_vol[int(cyl_i)] = 2
        combustion_slot_open_threshold_by_vol_m2[int(cyl_i)] = float(getattr(combustion_cfg_local, 'slot_open_threshold_m2', 1.0e-7) or 1.0e-7)
        combustion_slot_closed_threshold_by_vol_m2[int(cyl_i)] = float(getattr(combustion_cfg_local, 'slot_closed_threshold_m2', 1.0e-9) or 1.0e-9)
        combustion_compression_velocity_threshold_by_vol_m_per_s[int(cyl_i)] = float(getattr(combustion_cfg_local, 'compression_velocity_threshold_m_per_s', 0.02) or 0.02)
        injector_duration_by_vol_s[int(cyl_i)] = (
            float(getattr(combustion_cfg_local, 'injection_duration_s', 0.0) or 0.0)
            if getattr(combustion_cfg_local, 'injection_duration_s', None) is not None
            else float(getattr(combustion_cfg_local, 'injection_duration_ms', 0.0) or 0.0) * 1.0e-3
        )
        if is_hcci_diesel:
            start_deg = 0.0
            duration_value = float(combustion_cfg_local.duration_s) if combustion_cfg_local.duration_s is not None else float(combustion_cfg_local.duration_ms) * 1.0e-3
            ref_enum_value = float(builder._ref_enum('compression_tdc'))
            start_mode_enum = CombStartMode.AUTOIGNITION
            duration_mode_enum = CombDurationMode.TIME
            hcci_enabled_by_vol[int(cyl_i)] = 1
            hcci_tau_A_by_vol_s[int(cyl_i)] = float(combustion_cfg_local.tau_A_s)
            hcci_pressure_exponent_by_vol[int(cyl_i)] = float(combustion_cfg_local.tau_pressure_exponent)
            hcci_activation_temperature_by_vol_K[int(cyl_i)] = float(combustion_cfg_local.tau_activation_temperature_K)
            hcci_reference_pressure_by_vol_Pa[int(cyl_i)] = float(combustion_cfg_local.tau_reference_pressure_Pa)
            hcci_reference_lambda_by_vol[int(cyl_i)] = float(combustion_cfg_local.tau_reference_lambda)
            hcci_lambda_slowdown_exponent_by_vol[int(cyl_i)] = float(combustion_cfg_local.lambda_slowdown_exponent)
            hcci_residual_slowdown_factor_by_vol[int(cyl_i)] = float(combustion_cfg_local.residual_slowdown_factor)
            hcci_start_temperature_min_by_vol_K[int(cyl_i)] = float(combustion_cfg_local.start_temperature_min_K)
            hcci_start_pressure_min_by_vol_Pa[int(cyl_i)] = float(combustion_cfg_local.start_pressure_min_Pa)
            hcci_max_ignition_delay_by_vol_s[int(cyl_i)] = float(combustion_cfg_local.max_ignition_delay_s)
        else:
            start_deg, duration_value, ref_type, start_mode_enum, duration_mode_enum = _resolve_combustion_timing_for_free_piston(
                combustion_cfg_local,
                nominal_stroke_m,
                cycle_deg,
            )
            if int(ref_type) == int(AngleReference.COMPRESSION_TDC):
                ref_enum_value = float(builder._ref_enum('compression_tdc'))
            elif int(ref_type) == int(AngleReference.GAS_EXCHANGE_TDC):
                ref_enum_value = float(builder._ref_enum('gas_exchange_tdc'))
            else:
                ref_enum_value = float(builder._ref_enum(combustion_cfg_local.angle_reference))
        comb_row = np.array([
            float(CombustionModel.HCCI_DIESEL if is_hcci_diesel else CombustionModel.VIBE),
            float(start_deg),
            float(duration_value),
            float(combustion_cfg_local.a),
            float(combustion_cfg_local.m),
            float(comb_fuel_mass if comb_fuel_mass > 0.0 else q_total_J),
            float(comb_lhv if comb_fuel_mass > 0.0 else 1.0),
            ref_enum_value,
            float(start_mode_enum),
            float(duration_mode_enum),
        ], dtype=np.float64)
        vol_matrix[int(cyl_i), VolumeCol.COMB_ROW] = float(len(comb_rows))
        comb_rows.append(comb_row)
    if comb_rows:
        comb_matrix = np.asarray(comb_rows, dtype=np.float64)
    evap_matrix = np.zeros((0, len(EvapCol)), dtype=np.float64)
    conn_matrix, lift_table, alpha_table, cd_table, connection_names = build_connection_tables(
        builder,
        config=config,
        vol_matrix=vol_matrix,
        kin_matrix=kin_matrix,
        name_to_index=name_to_index,
        allow_valves=False,
        allow_slot_by_angle=False,
    )

    gas_props = build_gas_props(config)
    gas_thermo_model = build_gas_thermo_model(config)
    feature_flags = build_feature_flags(config)
    simulation = build_simulation_options(config, cycle_period_s)
    postprocessing = build_postprocessing_options(config)
    jac_sparsity = build_rhs_jacobian_sparsity(n_vol, conn_matrix, feature_flags, extra_state_count=2 * mechanical_dofs, dense_extra_coupling=True)
    jac_color_groups = greedy_color_columns(jac_sparsity)

    wall_bore_by_vol = np.zeros(n_vol, dtype=np.float64)
    wall_ups_by_vol = np.zeros(n_vol, dtype=np.float64)
    if synthetic_cylinder is not None and placeholder_cylinders:
        cyl_placeholder = placeholder_cylinders[0]
        wall_bore_by_vol[cyl_idx] = float(cyl_placeholder.kinematics.bore_m)
        wall_ups_by_vol[cyl_idx] = 2.0 * float(cyl_placeholder.kinematics.stroke_m) * float(config.engine.speed_rpm) / 60.0
    else:
        for cyl_i in cylinder_indices:
            cyl_cfg_i = cylinder_cfg_by_index.get(int(cyl_i))
            wall_bore_by_vol[int(cyl_i)] = float(cyl_cfg_i.kinematics.bore_m) if cyl_cfg_i is not None else float(_fp_piston_diameter_m(fp))
            stroke_m = float(cyl_cfg_i.kinematics.stroke_m) if cyl_cfg_i is not None else max(float(fp.mechanics.x_max_m) - float(fp.mechanics.x_min_m), 0.0)
            wall_ups_by_vol[int(cyl_i)] = 2.0 * stroke_m * float(config.engine.speed_rpm) / 60.0

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
            m_idx_i = int(state_layout.mass_index(i))
            u_idx_i = int(state_layout.energy_index(i))
            air_idx_i = int(state_layout.air_mass_index(i))
            burned_idx_i = int(state_layout.burned_mass_index(i))
            mass_i = float(y_init[m_idx_i])
            air_i = float(y_init[air_idx_i])
            burned_i = float(y_init[burned_idx_i])
            fuel_vapor_i = max(mass_i - air_i - burned_i, 0.0)
            temp_i = float(getattr(vol, 'initial_temperature_K', 300.0))
            _cp_i, cv_i, _R_i, _kappa_i = reduced_mixture_properties_from_temperature_quellen(temp_i, air_i, fuel_vapor_i, burned_i)
            y_init[u_idx_i] = mass_i * max(cv_i, cv_fallback) * temp_i

    combustion_cfg = cylinder_cfg_for_submodels.combustion if cylinder_cfg_for_submodels is not None else None
    cylinder_index_set = {int(idx) for idx in cylinder_indices}
    cylinder_slot_conn_indices = np.array([
        i for i in range(int(conn_matrix.shape[0]))
        if int(conn_matrix[i, ConnCol.TYPE]) == int(ConnectionType.SLOT)
        and (int(conn_matrix[i, ConnCol.FROM_VOL]) in cylinder_index_set or int(conn_matrix[i, ConnCol.TO_VOL]) in cylinder_index_set)
    ], dtype=np.int64)
    meta = FreePistonModelData(
        x0_m=float(fp.initial_conditions.x0_m),
        v0_m_per_s=float(fp.initial_conditions.v0_m_per_s),
        x_min_m=float(fp.mechanics.x_min_m),
        x_max_m=float(fp.mechanics.x_max_m),
        kinematics_type=_fp_kinematics_type(fp),
        rotary_angle_min_rad=_fp_rotary_angle_min_rad(fp),
        rotary_angle_max_rad=_fp_rotary_angle_max_rad(fp),
        rotary_effective_radius_m=_fp_rotary_effective_radius_m(fp),
        rotary_inertia_kg_m2=_fp_rotary_inertia_kg_m2(fp),
        moving_mass_kg=float(fp.mechanics.moving_mass_kg),
        piston_diameter_m=_fp_piston_diameter_m(fp),
        compression_ratio=_fp_compression_ratio(fp),
        piston_area_m2=_fp_piston_area_m2(fp),
        clearance_volume_m3=_fp_clearance_volume_m3(fp),
        cylinder_pressure_Pa=float(initial_cylinder_pressure_Pa),
        cylinder_temperature_K=float(initial_cylinder_temperature_K),
        initial_cylinder_volume_m3=float(initial_cylinder_volume_m3),
        initial_cylinder_mass_kg=float(initial_cylinder_mass_kg),
        initial_cylinder_internal_energy_J=float(initial_cylinder_internal_energy_J),
        bounce_pressure_Pa=float(bounce_geom.initial_pressure_Pa),
        bounce_temperature_K=float(bounce_geom.initial_temperature_K),
        friction_model=str(fp.friction.model),
        friction_fc_N=float(fp.friction.fc_N),
        friction_cv_Ns_per_m=float(fp.friction.cv_Ns_per_m),
        load_model=str(fp.load.model),
        load_damping_Ns_per_m=float(fp.load.damping_Ns_per_m),
        load_max_damping_Ns_per_m=float(fp.load.max_damping_Ns_per_m if fp.load.max_damping_Ns_per_m is not None else fp.load.damping_Ns_per_m),
        load_control_zone_m=float(fp.load.control_zone_m if fp.load.control_zone_m is not None else 0.0),
        load_power_target_W=float(fp.load.power_target_W if getattr(fp.load, 'power_target_W', None) is not None else 0.0),
        load_efficiency_0to1=float(fp.load.efficiency_0to1 if getattr(fp.load, 'efficiency_0to1', None) is not None else 1.0),
        load_min_velocity_m_per_s=float(fp.load.min_velocity_m_per_s if getattr(fp.load, 'min_velocity_m_per_s', None) is not None else 0.1),
        load_assist_velocity_threshold_m_per_s=float(fp.load.assist_velocity_threshold_m_per_s if getattr(fp.load, 'assist_velocity_threshold_m_per_s', None) is not None else 0.0),
        load_assist_force_N=float(fp.load.assist_force_N if getattr(fp.load, 'assist_force_N', None) is not None else 0.0),
        load_target_margin_m=float(fp.load.target_margin_m if getattr(fp.load, 'target_margin_m', None) is not None else 0.0),
        load_hard_margin_m=float(fp.load.hard_margin_m if getattr(fp.load, 'hard_margin_m', None) is not None else 0.0),
        load_stop_kp=float(fp.load.stop_kp if getattr(fp.load, 'stop_kp', None) is not None else 1.0),
        load_max_force_N=float(fp.load.max_force_N if getattr(fp.load, 'max_force_N', None) is not None else float('inf')),
        scavenging_enabled=bool(getattr(fp.scavenging, 'enabled', False)),
        scavenging_model=str(getattr(fp.scavenging, 'model', 'overlap_short_circuit_0d')),
        scavenging_factor=float(getattr(fp.scavenging, 'scavenging_factor', 1.25)),
        scavenging_max_trapping_efficiency=float(getattr(fp.scavenging, 'max_trapping_efficiency', 0.92)),
        scavenging_short_circuit_start_ratio=float(getattr(fp.scavenging, 'short_circuit_start_ratio', 0.70)),
        scavenging_short_circuit_slope=float(getattr(fp.scavenging, 'short_circuit_slope', 0.35)),
        scavenging_max_short_circuit_fraction=float(getattr(fp.scavenging, 'max_short_circuit_fraction', 0.35)),
        scavenging_min_residual_fraction=float(getattr(fp.scavenging, 'min_residual_fraction', 0.03)),
        bounce_model=str(bounce_geom.model),
        bounce_chamber_diameter_m=float(bounce_geom.chamber_diameter_m),
        bounce_chamber_length_m=float(bounce_geom.chamber_length_m),
        bounce_compression_ratio=float(bounce_geom.compression_ratio),
        bounce_chamber_cross_section_m2=float(bounce_geom.chamber_cross_section_m2),
        bounce_swept_volume_m3=float(bounce_geom.swept_volume_m3),
        bounce_area_m2=float(bounce_geom.area_m2),
        bounce_chamber_min_volume_m3=float(bounce_geom.chamber_min_volume_m3),
        bounce_chamber_volume0_m3=float(bounce_geom.chamber_volume0_m3),
        bounce_p0_Pa=float(bounce_geom.p0_Pa),
        bounce_polytropic_exponent=float(bounce_geom.polytropic_exponent),
        x_state_index=int(x_idx),
        v_state_index=int(v_idx),
        mechanical_dofs=int(mechanical_dofs),
        mechanical_x_state_indices=mechanical_x_indices,
        mechanical_v_state_indices=mechanical_v_indices,
        volume_mechanical_dof=volume_mechanical_dof,
        volume_mechanical_sign=volume_mechanical_sign,
        combustion_fueling_mode=str(getattr(combustion_cfg, 'fueling_mode', 'fixed_energy') or 'fixed_energy'),
        combustion_fueling_mode_by_vol=combustion_fueling_mode_by_vol,
        combustion_lambda_target=float(getattr(combustion_cfg, 'lambda_target', 0.0) or 0.0),
        combustion_afr_stoich_kg_air_per_kg_fuel=float(getattr(combustion_cfg, 'afr_stoich_kg_air_per_kg_fuel', 14.5) or 14.5),
        combustion_efficiency_0to1=float(getattr(combustion_cfg, 'combustion_efficiency_0to1', 1.0) or 1.0),
        combustion_lhv_J_per_kg=float(getattr(combustion_cfg, 'lhv_J_per_kg', 0.0) or 0.0),
        combustion_slot_open_threshold_m2=float(getattr(combustion_cfg, 'slot_open_threshold_m2', 1.0e-7) or 1.0e-7),
        combustion_slot_closed_threshold_m2=float(getattr(combustion_cfg, 'slot_closed_threshold_m2', 1.0e-9) or 1.0e-9),
        combustion_compression_velocity_threshold_m_per_s=float(getattr(combustion_cfg, 'compression_velocity_threshold_m_per_s', 0.02) or 0.02),
        injector_duration_s=(float(getattr(combustion_cfg, 'injection_duration_s', 0.0) or 0.0) if getattr(combustion_cfg, 'injection_duration_s', None) is not None else float(getattr(combustion_cfg, 'injection_duration_ms', 0.0) or 0.0) * 1.0e-3),
        combustion_slot_open_threshold_by_vol_m2=combustion_slot_open_threshold_by_vol_m2,
        combustion_slot_closed_threshold_by_vol_m2=combustion_slot_closed_threshold_by_vol_m2,
        combustion_compression_velocity_threshold_by_vol_m_per_s=combustion_compression_velocity_threshold_by_vol_m_per_s,
        injector_duration_by_vol_s=injector_duration_by_vol_s,
        combustion_comb_idx=int(vol_matrix[cyl_idx, VolumeCol.COMB_ROW]),
        combustion_cylinder_slot_conn_indices=cylinder_slot_conn_indices,
        hcci_enabled_by_vol=hcci_enabled_by_vol,
        hcci_tau_A_by_vol_s=hcci_tau_A_by_vol_s,
        hcci_pressure_exponent_by_vol=hcci_pressure_exponent_by_vol,
        hcci_activation_temperature_by_vol_K=hcci_activation_temperature_by_vol_K,
        hcci_reference_pressure_by_vol_Pa=hcci_reference_pressure_by_vol_Pa,
        hcci_reference_lambda_by_vol=hcci_reference_lambda_by_vol,
        hcci_lambda_slowdown_exponent_by_vol=hcci_lambda_slowdown_exponent_by_vol,
        hcci_residual_slowdown_factor_by_vol=hcci_residual_slowdown_factor_by_vol,
        hcci_start_temperature_min_by_vol_K=hcci_start_temperature_min_by_vol_K,
        hcci_start_pressure_min_by_vol_Pa=hcci_start_pressure_min_by_vol_Pa,
        hcci_max_ignition_delay_by_vol_s=hcci_max_ignition_delay_by_vol_s,
        runtime_scavenging_transfer_in_by_vol_kg_per_s=np.zeros(n_vol, dtype=np.float64),
        runtime_scavenging_exhaust_out_by_vol_kg_per_s=np.zeros(n_vol, dtype=np.float64),
        runtime_scavenging_burned_correction_by_vol_kg_per_s=np.zeros(n_vol, dtype=np.float64),
        runtime_scavenging_short_circuit_fraction_by_vol=np.zeros(n_vol, dtype=np.float64),
        runtime_injector_active_by_vol=np.zeros(n_vol, dtype=np.int64),
        runtime_injector_time_by_vol_s=np.zeros(n_vol, dtype=np.float64),
        runtime_injector_end_time_by_vol_s=np.zeros(n_vol, dtype=np.float64),
        runtime_injector_target_fuel_by_vol_kg=np.zeros(n_vol, dtype=np.float64),
        runtime_injector_injected_by_vol_kg=np.zeros(n_vol, dtype=np.float64),
        runtime_injector_rate_by_vol_kg_per_s=np.zeros(n_vol, dtype=np.float64),
    )

    bundle = ModelBundle(
        y_init=y_init,
        architecture='free_piston',
        state_layout=state_layout,
        free_piston=meta,
        vol_matrix=vol_matrix,
        kin_matrix=kin_matrix,
        conn_matrix=conn_matrix,
        wall_matrix=wall_matrix,
        wall_ref_matrix=wall_ref_matrix,
        wall_ref_matrix_safe=wall_ref_matrix_safe,
        wall_bore_by_vol=wall_bore_by_vol,
        wall_ups_by_vol=wall_ups_by_vol,
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
        combustion_lambda_target_by_vol=combustion_lambda_target_by_vol,
        combustion_efficiency_by_vol=combustion_efficiency_by_vol,
        combustion_lhv_by_vol=combustion_lhv_by_vol,
    )
    bootstrap_free_piston_combustion_latch(bundle)
    return bundle
