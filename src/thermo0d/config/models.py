from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal, Union
import math

from thermo0d.config.schema_meta import SOLVER_KINDS
from thermo0d.physics.beck import BECK_COOL_FLAME_FUEL_NAMES

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictFloat, StrictInt, StrictStr, field_validator, model_validator


def _resolve_optional_length_m(value_m: float | None, value_mm: float | None, *, field_m: str, field_mm: str, required: bool, strictly_positive: bool) -> float | None:
    has_m = value_m is not None
    has_mm = value_mm is not None
    if has_m and has_mm:
        raise ValueError(f"Use either {field_m} or {field_mm}, not both")
    if not has_m and not has_mm:
        if required:
            raise ValueError(f"Either {field_m} or {field_mm} must be provided")
        return None
    value = float(value_m) if has_m else float(value_mm) * 1.0e-3
    if strictly_positive:
        if value <= 0.0:
            raise ValueError(f"{field_m}/{field_mm} must resolve to > 0")
    elif value < 0.0:
        raise ValueError(f"{field_m}/{field_mm} must resolve to >= 0")
    return value


def _resolve_area_m2(area_m2: float | None, diameter_mm: float | None, *, area_field: str = "area_m2", diameter_field: str = "diameter_mm") -> float:
    has_area = area_m2 is not None
    has_diameter = diameter_mm is not None
    if has_area and has_diameter:
        raise ValueError(f"Use either {area_field} or {diameter_field}, not both")
    if not has_area and not has_diameter:
        raise ValueError(f"Either {area_field} or {diameter_field} must be provided")
    if has_area:
        area = float(area_m2)
    else:
        diameter_m = float(diameter_mm) * 1.0e-3
        area = 0.25 * math.pi * diameter_m * diameter_m
    if area <= 0.0:
        raise ValueError(f"{area_field}/{diameter_field} must resolve to > 0")
    return area


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SolverConfig(StrictBaseModel):
    kind: StrictStr
    rtol: StrictFloat
    atol: StrictFloat


class SimulationConfig(StrictBaseModel):
    dt_s: StrictFloat
    total_cycles: StrictInt
    save_last_cycles: StrictInt
    simulationtime: StrictFloat | None = None
    solver: SolverConfig

    @model_validator(mode="after")
    def validate_values(self) -> "SimulationConfig":
        if self.dt_s <= 0.0:
            raise ValueError("dt_s must be > 0")
        if self.total_cycles <= 0:
            raise ValueError("total_cycles must be > 0")
        if self.save_last_cycles <= 0 or self.save_last_cycles > self.total_cycles:
            raise ValueError("save_last_cycles must satisfy 0 < save_last_cycles <= total_cycles")
        if self.simulationtime is not None and self.simulationtime <= 0.0:
            raise ValueError("simulationtime must be > 0 when provided")
        if self.solver.kind not in SOLVER_KINDS:
            raise ValueError(f"solver.kind must be one of {SOLVER_KINDS}")
        return self


class TimeSamplingConfig(StrictBaseModel):
    mode: Literal["time"]
    step_s: StrictFloat

    @model_validator(mode="after")
    def validate_value(self) -> "TimeSamplingConfig":
        if self.step_s <= 0.0:
            raise ValueError("step_s must be > 0")
        return self


class CrankAngleSamplingConfig(StrictBaseModel):
    mode: Literal["crank_angle"]
    step_deg: StrictFloat

    @model_validator(mode="after")
    def validate_value(self) -> "CrankAngleSamplingConfig":
        if self.step_deg <= 0.0:
            raise ValueError("step_deg must be > 0")
        return self


SamplingConfig = Annotated[
    Union[TimeSamplingConfig, CrankAngleSamplingConfig],
    Field(discriminator="mode"),
]


class LastCycleUniformAngleExportConfig(StrictBaseModel):
    enabled: StrictBool = False
    step_deg: StrictFloat = 1.0

    @model_validator(mode="after")
    def validate_values(self) -> "LastCycleUniformAngleExportConfig":
        if self.step_deg <= 0.0:
            raise ValueError("step_deg must be > 0")
        return self


class FreePistonLastUtOtUtExportConfig(StrictBaseModel):
    enabled: StrictBool = False
    step_deg: StrictFloat = 1.0
    axis_min_deg: StrictFloat = 0.0
    axis_max_deg: StrictFloat = 360.0

    @model_validator(mode="after")
    def validate_values(self) -> "FreePistonLastUtOtUtExportConfig":
        if self.step_deg <= 0.0:
            raise ValueError("step_deg must be > 0")
        if self.axis_max_deg <= self.axis_min_deg:
            raise ValueError("axis_max_deg must be > axis_min_deg")
        return self


class RhsDerivativesExportConfig(StrictBaseModel):
    enabled: StrictBool = False
    path: StrictStr | None = None

    @model_validator(mode="after")
    def validate_values(self) -> "RhsDerivativesExportConfig":
        if self.path is not None and not self.path.strip():
            raise ValueError("rhs_derivatives_export.path must not be empty when provided")
        return self


class CheckReportConfig(StrictBaseModel):
    enabled: StrictBool = True
    html_enabled: StrictBool = False


class PlotLayoutEntryConfig(StrictBaseModel):
    enabled: StrictBool = True
    path: StrictStr
    prefix: StrictStr = ""

    @model_validator(mode="after")
    def validate_values(self) -> "PlotLayoutEntryConfig":
        if not self.path.strip():
            raise ValueError("plots.layouts.entries[].path must not be empty")
        return self


class PlotLayoutsConfig(StrictBaseModel):
    auto_create_defaults: StrictBool = True
    entries: list[PlotLayoutEntryConfig] = Field(default_factory=list)


class PlotsConfig(StrictBaseModel):
    enabled: StrictBool = True
    source: Literal["last_cycle_uniform", "export_rows"] = "last_cycle_uniform"
    output_dir: StrictStr | None = None
    layouts: PlotLayoutsConfig = Field(default_factory=PlotLayoutsConfig)


class ConsoleSectionConfig(StrictBaseModel):
    enabled: StrictBool = True


class ConsoleOutputConfig(StrictBaseModel):
    run_summary: ConsoleSectionConfig = Field(default_factory=ConsoleSectionConfig)
    cycle_summary: ConsoleSectionConfig = Field(default_factory=ConsoleSectionConfig)
    check_report: ConsoleSectionConfig = Field(default_factory=ConsoleSectionConfig)
    geometry: ConsoleSectionConfig = Field(default_factory=ConsoleSectionConfig)


class PostprocessingConfig(StrictBaseModel):
    outdir: StrictStr | None = None
    auto_update_initial_conditions: StrictBool = True
    csv_enabled: StrictBool = True
    csv_path: StrictStr = "results/out.csv"
    csv_separator: StrictStr = ";"
    csv_export_layout: StrictStr | None = None
    csv_export_mode: Literal["auto", "all", "selected"] = "auto"
    csv_export_missing_layout: Literal["warn_all", "fail"] = "warn_all"
    csv_export_unknown_signals: Literal["warn_empty", "fail"] = "warn_empty"
    excel_enabled: StrictBool = False
    excel_path: StrictStr = "results/out.xlsx"
    sampling: SamplingConfig
    final_cycle_uniform_angle_export: LastCycleUniformAngleExportConfig = Field(default_factory=LastCycleUniformAngleExportConfig)
    free_piston_last_ut_ot_ut_export: FreePistonLastUtOtUtExportConfig = Field(default_factory=FreePistonLastUtOtUtExportConfig)
    rhs_derivatives_export: RhsDerivativesExportConfig = Field(default_factory=RhsDerivativesExportConfig)
    check_report: CheckReportConfig = Field(default_factory=CheckReportConfig)
    plots: PlotsConfig = Field(default_factory=PlotsConfig)
    console: ConsoleOutputConfig = Field(default_factory=ConsoleOutputConfig)

    @model_validator(mode="after")
    def validate_values(self) -> "PostprocessingConfig":
        if self.outdir is not None and not self.outdir.strip():
            raise ValueError("outdir must not be empty when provided")
        if len(self.csv_separator) != 1:
            raise ValueError("csv_separator must be a single character")
        if not self.csv_path.strip():
            raise ValueError("csv_path must not be empty")
        if self.csv_export_layout is not None and not self.csv_export_layout.strip():
            raise ValueError("csv_export_layout must not be empty when provided")
        if not self.excel_path.strip():
            raise ValueError("excel_path must not be empty")
        return self


class GasPropertiesConfig(StrictBaseModel):
    cp_J_per_kgK: StrictFloat
    cv_J_per_kgK: StrictFloat
    R_J_per_kgK: StrictFloat
    thermo_model: Literal["constant", "promo"] = "constant"

    @field_validator("thermo_model", mode="before")
    @classmethod
    def normalize_thermo_model(cls, value):
        if value == "quellen_step1":
            return "promo"
        return value

    @model_validator(mode="after")
    def validate_physics(self) -> "GasPropertiesConfig":
        if self.cp_J_per_kgK <= 0.0 or self.cv_J_per_kgK <= 0.0 or self.R_J_per_kgK <= 0.0:
            raise ValueError("All gas properties must be > 0")
        if self.cp_J_per_kgK <= self.cv_J_per_kgK:
            raise ValueError("cp must be > cv")
        if self.thermo_model not in ("constant", "promo"):
            raise ValueError("thermo_model must be 'constant' or 'promo'")
        return self



class FeatureToggleConfig(StrictBaseModel):
    mass_flow: StrictBool
    wall_heat: StrictBool
    combustion: StrictBool
    evaporation: StrictBool
    pv_work: StrictBool


class ModelingConfig(StrictBaseModel):
    architecture: Literal["classic", "free_piston"] = "classic"


class EngineConfig(StrictBaseModel):

    cycle_type: Literal["2t", "4t"]
    speed_rpm: StrictFloat

    @model_validator(mode="after")
    def validate_speed(self) -> "EngineConfig":
        if self.speed_rpm <= 0.0:
            raise ValueError("speed_rpm must be > 0")
        return self


class DisabledSubmodelConfig(StrictBaseModel):
    model: Literal["none"]
    start_mode: Literal["angle", "compression_hub", "hign_position"] | None = None
    start_deg: StrictFloat | None = None
    duration_mode: Literal["angle", "compression_hub", "time"] | None = None
    duration_deg: StrictFloat | None = None
    start_hub_m: StrictFloat | None = None
    hign_m: StrictFloat | None = None
    hign_mm: StrictFloat | None = None
    duration_hub_m: StrictFloat | None = None
    duration_s: StrictFloat | None = None
    duration_ms: StrictFloat | None = None
    injection_duration_s: StrictFloat | None = None
    injection_duration_ms: StrictFloat | None = None
    a: StrictFloat | None = None
    m: StrictFloat | None = None
    fuel_mass_per_cycle_kg: StrictFloat | None = None
    lhv_J_per_kg: StrictFloat | None = None
    lambda_target: StrictFloat | None = None
    afr_stoich_kg_air_per_kg_fuel: StrictFloat | None = None
    combustion_efficiency_0to1: StrictFloat | None = None
    fueling_mode: Literal["fixed_energy", "lambda_from_cylinder_mass_at_slot_close"] | None = None
    slot_open_threshold_m2: StrictFloat | None = None
    slot_closed_threshold_m2: StrictFloat | None = None
    compression_velocity_threshold_m_per_s: StrictFloat | None = None
    evaporated_mass_per_cycle_kg: StrictFloat | None = None
    latent_heat_J_per_kg: StrictFloat | None = None
    angle_reference: Literal["absolute", "compression_tdc", "gas_exchange_tdc"] | None = None
    c1: StrictFloat | None = None
    c2: StrictFloat | None = None
    c3: StrictFloat | None = None
    wall_temperature_K: StrictFloat | None = None
    wall_area_m2: StrictFloat | None = None


class DisabledCombustionConfig(StrictBaseModel):
    model: Literal["none"]
    start_mode: Literal["angle", "compression_hub", "hign_position"] | None = None
    start_deg: StrictFloat | None = None
    duration_mode: Literal["angle", "compression_hub", "time"] | None = None
    duration_deg: StrictFloat | None = None
    start_hub_m: StrictFloat | None = None
    hign_m: StrictFloat | None = None
    hign_mm: StrictFloat | None = None
    duration_hub_m: StrictFloat | None = None
    duration_s: StrictFloat | None = None
    duration_ms: StrictFloat | None = None
    injection_duration_s: StrictFloat | None = None
    injection_duration_ms: StrictFloat | None = None
    a: StrictFloat | None = None
    m: StrictFloat | None = None
    fuel_mass_per_cycle_kg: StrictFloat | None = None
    lhv_J_per_kg: StrictFloat | None = None
    lambda_target: StrictFloat | None = None
    afr_stoich_kg_air_per_kg_fuel: StrictFloat | None = None
    combustion_efficiency_0to1: StrictFloat | None = None
    fueling_mode: Literal["fixed_energy", "lambda_from_cylinder_mass_at_slot_close"] | None = None
    slot_open_threshold_m2: StrictFloat | None = None
    slot_closed_threshold_m2: StrictFloat | None = None
    compression_velocity_threshold_m_per_s: StrictFloat | None = None
    angle_reference: Literal["absolute", "compression_tdc", "gas_exchange_tdc"] | None = None


class DisabledEvaporationConfig(StrictBaseModel):
    model: Literal["none"]
    start_deg: StrictFloat | None = None
    duration_deg: StrictFloat | None = None
    evaporated_mass_per_cycle_kg: StrictFloat | None = None
    latent_heat_J_per_kg: StrictFloat | None = None
    angle_reference: Literal["absolute", "compression_tdc", "gas_exchange_tdc"] | None = None


class WoschniHeatTransferConfig(StrictBaseModel):
    model: Literal["woschni"]
    variant: Literal["legacy", "promo", "gt", "classic", "swirl", "huber"] = "legacy"
    c1: StrictFloat | None = None
    c2: StrictFloat | None = None
    c3: StrictFloat | None = None
    wall_temperature_K: StrictFloat
    wall_area_m2: StrictFloat
    multiplier: StrictFloat = 1.0
    cucm: StrictFloat = 0.0
    swirl_number: StrictFloat = 0.0
    imep_bar: StrictFloat = 0.0
    dp_mode: Literal["off", "instant", "motored"] = "off"
    reference_state_mode: Literal["none", "pre_combustion_latch", "cycle_start_latch"] = "none"
    phase_mode: Literal["legacy", "promo", "classic", "gt"] = "legacy"

    @model_validator(mode="after")
    def validate_woschni(self) -> "WoschniHeatTransferConfig":
        if self.wall_temperature_K <= 0.0:
            raise ValueError("wall_temperature_K must be > 0")
        if self.wall_area_m2 < 0.0:
            raise ValueError("wall_area_m2 must be >= 0")
        if self.multiplier < 0.0:
            raise ValueError("multiplier must be >= 0")
        if self.variant == "legacy" and (self.c1 is None or self.c2 is None or self.c3 is None):
            raise ValueError("variant=legacy requires c1, c2 and c3")
        return self


class DisabledWallTemperatureConfig(StrictBaseModel):
    model: Literal["none"]


class WallTemperatureZoneConfig(StrictBaseModel):
    initial_temperature_K: StrictFloat
    coolant_temperature_K: StrictFloat
    lambda_W_per_mK: StrictFloat
    wall_thickness_m: StrictFloat
    area_m2: StrictFloat

    @model_validator(mode="after")
    def validate_values(self) -> "WallTemperatureZoneConfig":
        if self.initial_temperature_K <= 0.0:
            raise ValueError("initial_temperature_K must be > 0")
        if self.coolant_temperature_K <= 0.0:
            raise ValueError("coolant_temperature_K must be > 0")
        if self.lambda_W_per_mK <= 0.0:
            raise ValueError("lambda_W_per_mK must be > 0")
        if self.wall_thickness_m <= 0.0:
            raise ValueError("wall_thickness_m must be > 0")
        if self.area_m2 <= 0.0:
            raise ValueError("area_m2 must be > 0")
        return self


class CycleAverageWallTemperatureConfig(StrictBaseModel):
    model: Literal["cycle_average"]
    relaxation: StrictFloat = 0.3
    cylinder: WallTemperatureZoneConfig
    head: WallTemperatureZoneConfig
    piston: WallTemperatureZoneConfig

    @model_validator(mode="after")
    def validate_values(self) -> "CycleAverageWallTemperatureConfig":
        if self.relaxation <= 0.0:
            raise ValueError("relaxation must be > 0")
        return self


class VibeCombustionConfig(StrictBaseModel):
    model: Literal["vibe"]
    start_mode: Literal["angle", "compression_hub", "hign_position"] = "angle"
    start_deg: StrictFloat | None = None
    duration_mode: Literal["angle", "compression_hub", "time"] | None = None
    duration_deg: StrictFloat | None = None
    start_hub_m: StrictFloat | None = None
    hign_m: StrictFloat | None = None
    hign_mm: StrictFloat | None = None
    duration_hub_m: StrictFloat | None = None
    duration_s: StrictFloat | None = None
    duration_ms: StrictFloat | None = None
    injection_duration_s: StrictFloat | None = None
    injection_duration_ms: StrictFloat | None = None
    a: StrictFloat
    m: StrictFloat
    fuel_mass_per_cycle_kg: StrictFloat | None = None
    lhv_J_per_kg: StrictFloat | None = None
    added_energy_per_cycle_J: StrictFloat | None = None
    energy_coupling: Literal["none", "stroke_ratio"] = "none"
    stroke_reference_m: StrictFloat | None = None
    stroke_exponent: StrictFloat = 1.0
    lambda_target: StrictFloat | None = None
    afr_stoich_kg_air_per_kg_fuel: StrictFloat = 14.5
    combustion_efficiency_0to1: StrictFloat = 1.0
    fueling_mode: Literal["fixed_energy", "lambda_from_cylinder_mass_at_slot_close", "lambda_from_cylinder_air_at_slot_close_vapor_injector"] = "fixed_energy"
    slot_open_threshold_m2: StrictFloat = 1.0e-7
    slot_closed_threshold_m2: StrictFloat = 1.0e-9
    compression_velocity_threshold_m_per_s: StrictFloat = 0.02
    angle_reference: Literal["absolute", "compression_tdc", "gas_exchange_tdc"] = "compression_tdc"

    @model_validator(mode="after")
    def validate_values(self) -> "VibeCombustionConfig":
        if self.start_mode == "angle":
            if self.start_deg is None:
                raise ValueError("start_deg is required when start_mode = 'angle'")
            if self.start_hub_m is not None:
                raise ValueError("start_hub_m is only allowed when start_mode = 'compression_hub'")
            if self.hign_m is not None or self.hign_mm is not None:
                raise ValueError("hign_m/hign_mm is only allowed when start_mode = 'hign_position'")
        elif self.start_mode == "compression_hub":
            if self.start_hub_m is None:
                raise ValueError("start_hub_m is required when start_mode = 'compression_hub'")
            if self.start_hub_m < 0.0:
                raise ValueError("start_hub_m must be >= 0")
            if self.start_deg is not None:
                raise ValueError("start_deg is only allowed when start_mode = 'angle'")
            if self.hign_m is not None or self.hign_mm is not None:
                raise ValueError("hign_m/hign_mm is only allowed when start_mode = 'hign_position'")
        else:
            has_hign_m = self.hign_m is not None
            has_hign_mm = self.hign_mm is not None
            if has_hign_m == has_hign_mm:
                raise ValueError("Use exactly one of hign_m or hign_mm when start_mode = 'hign_position'")
            resolved_hign_m = float(self.hign_m) if has_hign_m else float(self.hign_mm) * 1.0e-3
            if resolved_hign_m <= 0.0:
                raise ValueError("hign_m/hign_mm must resolve to > 0")
            if self.start_deg is not None:
                raise ValueError("start_deg is only allowed when start_mode = 'angle'")
            if self.start_hub_m is not None:
                raise ValueError("start_hub_m is only allowed when start_mode = 'compression_hub'")

        resolved_duration_mode = self.duration_mode
        if resolved_duration_mode is None:
            if self.duration_s is not None or self.duration_ms is not None:
                resolved_duration_mode = "time"
            elif self.duration_hub_m is not None and self.start_mode == "compression_hub":
                resolved_duration_mode = "compression_hub"
            else:
                resolved_duration_mode = "angle"

        if self.start_mode == "hign_position" and resolved_duration_mode != "time":
            raise ValueError("start_mode = 'hign_position' requires duration_mode = 'time'")

        if resolved_duration_mode == "angle":
            if self.duration_deg is None:
                raise ValueError("duration_deg is required when duration_mode = 'angle'")
            if self.duration_deg <= 0.0:
                raise ValueError("duration_deg must be > 0")
            if self.duration_hub_m is not None:
                raise ValueError("duration_hub_m is only allowed when duration_mode = 'compression_hub'")
            if self.duration_s is not None or self.duration_ms is not None:
                raise ValueError("duration_s/duration_ms is only allowed when duration_mode = 'time'")
        elif resolved_duration_mode == "compression_hub":
            if self.duration_hub_m is None:
                raise ValueError("duration_hub_m is required when duration_mode = 'compression_hub'")
            if self.duration_hub_m <= 0.0:
                raise ValueError("duration_hub_m must be > 0")
            if self.duration_deg is not None:
                raise ValueError("duration_deg is only allowed when duration_mode = 'angle'")
            if self.duration_s is not None or self.duration_ms is not None:
                raise ValueError("duration_s/duration_ms is only allowed when duration_mode = 'time'")
        else:
            has_duration_s = self.duration_s is not None
            has_duration_ms = self.duration_ms is not None
            if has_duration_s == has_duration_ms:
                raise ValueError("Use exactly one of duration_s or duration_ms when duration_mode = 'time'")
            resolved_duration_s = float(self.duration_s) if has_duration_s else float(self.duration_ms) * 1.0e-3
            if resolved_duration_s <= 0.0:
                raise ValueError("duration_s/duration_ms must resolve to > 0")
            if self.duration_deg is not None:
                raise ValueError("duration_deg is only allowed when duration_mode = 'angle'")
            if self.duration_hub_m is not None:
                raise ValueError("duration_hub_m is only allowed when duration_mode = 'compression_hub'")

        if self.a <= 0.0:
            raise ValueError("a must be > 0")
        if self.m < 0.0:
            raise ValueError("m must be >= 0")
        has_direct_energy = self.added_energy_per_cycle_J is not None
        has_fuel_pair = self.fuel_mass_per_cycle_kg is not None or self.lhv_J_per_kg is not None
        if self.fueling_mode == "fixed_energy":
            if has_direct_energy and has_fuel_pair:
                raise ValueError("Use either added_energy_per_cycle_J or fuel_mass_per_cycle_kg + lhv_J_per_kg, not both")
            if not has_direct_energy and not (self.fuel_mass_per_cycle_kg is not None and self.lhv_J_per_kg is not None):
                raise ValueError("Vibe combustion requires either added_energy_per_cycle_J or fuel_mass_per_cycle_kg + lhv_J_per_kg")
        elif self.fueling_mode == "lambda_from_cylinder_mass_at_slot_close":
            if has_direct_energy or self.fuel_mass_per_cycle_kg is not None:
                raise ValueError("fueling_mode='lambda_from_cylinder_mass_at_slot_close' may not use added_energy_per_cycle_J or fuel_mass_per_cycle_kg")
            if self.lambda_target is None or self.lambda_target <= 0.0:
                raise ValueError("lambda_target must be > 0 when fueling_mode='lambda_from_cylinder_mass_at_slot_close'")
            if self.lhv_J_per_kg is None or self.lhv_J_per_kg <= 0.0:
                raise ValueError("lhv_J_per_kg must be > 0 when fueling_mode='lambda_from_cylinder_mass_at_slot_close'")
        else:
            if has_direct_energy or self.fuel_mass_per_cycle_kg is not None:
                raise ValueError("fueling_mode='lambda_from_cylinder_air_at_slot_close_vapor_injector' may not use added_energy_per_cycle_J or fuel_mass_per_cycle_kg")
            if self.lambda_target is None or self.lambda_target <= 0.0:
                raise ValueError("lambda_target must be > 0 when fueling_mode='lambda_from_cylinder_air_at_slot_close_vapor_injector'")
            if self.lhv_J_per_kg is None or self.lhv_J_per_kg <= 0.0:
                raise ValueError("lhv_J_per_kg must be > 0 when fueling_mode='lambda_from_cylinder_air_at_slot_close_vapor_injector'")
            has_inj_s = self.injection_duration_s is not None
            has_inj_ms = self.injection_duration_ms is not None
            if has_inj_s == has_inj_ms:
                raise ValueError("Use exactly one of injection_duration_s or injection_duration_ms when fueling_mode='lambda_from_cylinder_air_at_slot_close_vapor_injector'")
            resolved_inj_s = float(self.injection_duration_s) if has_inj_s else float(self.injection_duration_ms) * 1.0e-3
            if resolved_inj_s <= 0.0:
                raise ValueError("injection_duration_s/injection_duration_ms must resolve to > 0")
        if self.fuel_mass_per_cycle_kg is not None and self.fuel_mass_per_cycle_kg <= 0.0:
            raise ValueError("fuel_mass_per_cycle_kg must be > 0")
        if self.lhv_J_per_kg is not None and self.lhv_J_per_kg <= 0.0:
            raise ValueError("lhv_J_per_kg must be > 0")
        if self.added_energy_per_cycle_J is not None and self.added_energy_per_cycle_J <= 0.0:
            raise ValueError("added_energy_per_cycle_J must be > 0")
        if self.lambda_target is not None and self.lambda_target <= 0.0:
            raise ValueError("lambda_target must be > 0 when provided")
        if self.afr_stoich_kg_air_per_kg_fuel <= 0.0:
            raise ValueError("afr_stoich_kg_air_per_kg_fuel must be > 0")
        if not (0.0 < self.combustion_efficiency_0to1 <= 1.0):
            raise ValueError("combustion_efficiency_0to1 must be > 0 and <= 1")
        if self.slot_open_threshold_m2 < 0.0:
            raise ValueError("slot_open_threshold_m2 must be >= 0")
        if self.slot_closed_threshold_m2 < 0.0:
            raise ValueError("slot_closed_threshold_m2 must be >= 0")
        if self.slot_closed_threshold_m2 > self.slot_open_threshold_m2:
            raise ValueError("slot_closed_threshold_m2 must be <= slot_open_threshold_m2")
        if self.compression_velocity_threshold_m_per_s < 0.0:
            raise ValueError("compression_velocity_threshold_m_per_s must be >= 0")
        if self.energy_coupling == "stroke_ratio":
            if self.stroke_reference_m is None or self.stroke_reference_m <= 0.0:
                raise ValueError("stroke_reference_m must be > 0 when energy_coupling = 'stroke_ratio'")
        elif self.stroke_reference_m is not None and self.stroke_reference_m <= 0.0:
            raise ValueError("stroke_reference_m must be > 0 when provided")
        if self.stroke_exponent < 0.0:
            raise ValueError("stroke_exponent must be >= 0")
        return self


class HcciDieselCombustionConfig(StrictBaseModel):
    model: Literal["hcci_diesel"]
    ignition_model: Literal["livengood_wu", "beck_2003_1_arrhenius", "beck_2003_two_stage"] = "livengood_wu"
    burn_model: Literal["wiebe_autoignition", "vibe-beck"] = "wiebe_autoignition"
    duration_mode: Literal["time"] = "time"
    duration_s: StrictFloat | None = None
    duration_ms: StrictFloat | None = None
    a: StrictFloat = 6.9
    m: StrictFloat = 2.0
    fueling_mode: Literal["lambda_from_cylinder_mass_at_slot_close"] = "lambda_from_cylinder_mass_at_slot_close"
    lambda_target: StrictFloat
    lhv_J_per_kg: StrictFloat
    afr_stoich_kg_air_per_kg_fuel: StrictFloat = 14.5
    combustion_efficiency_0to1: StrictFloat = 0.96
    slot_open_threshold_m2: StrictFloat = 1.0e-7
    slot_closed_threshold_m2: StrictFloat = 1.0e-9
    compression_velocity_threshold_m_per_s: StrictFloat = 0.02
    tau_A_s: StrictFloat = 2.5e-6
    tau_pressure_exponent: StrictFloat = 1.2
    tau_activation_temperature_K: StrictFloat = 15000.0
    tau_activation_energy_J_per_kg: StrictFloat | None = None
    tau_reference_pressure_Pa: StrictFloat = 1000000.0
    tau_reference_lambda: StrictFloat = 1.4
    lambda_slowdown_exponent: StrictFloat = 0.7
    residual_slowdown_factor: StrictFloat = 1.5
    beck_c1_s: StrictFloat = 1.0e-5
    beck_c2: StrictFloat = -1.2
    beck_reference_pressure_bar: StrictFloat = 1.0
    beck_reference_o2_percent: StrictFloat = 20.94
    beck_cf_fuel_name: StrictStr = "Diesel 2"
    cool_flame_enabled: StrictBool = False
    cool_flame_burn_model: Literal["gamma", "vibe-beck_CF", "vibe-beck"] = "gamma"
    cool_flame_energy_fraction: StrictFloat = 0.08
    cool_flame_duration_ms: StrictFloat = 0.3409
    cool_flame_a: StrictFloat = 6.9
    cool_flame_m: StrictFloat = 2.0
    # Beck Tabelle 6.2, Diesel 2, dQBmax: c1..c5/c0 in model order.
    cool_flame_dqmax_c1: StrictFloat = 0.363
    cool_flame_dqmax_c2: StrictFloat = -0.333
    cool_flame_dqmax_c3: StrictFloat = 1.424
    cool_flame_dqmax_c4: StrictFloat = 0.155
    cool_flame_dqmax_c5: StrictFloat = 0.0
    cool_flame_dqmax_c0: StrictFloat = 7.5e-3
    # Beck Tabelle 6.2, Diesel 2, Delta phi max.
    cool_flame_duration_c1: StrictFloat = -0.071
    cool_flame_duration_c2: StrictFloat = -8.5e-3
    cool_flame_duration_c3: StrictFloat = 0.016
    cool_flame_duration_c4: StrictFloat = -0.241
    cool_flame_duration_c5: StrictFloat = -0.645
    cool_flame_duration_c0: StrictFloat = 340.9
    start_temperature_min_K: StrictFloat = 780.0
    start_pressure_min_Pa: StrictFloat = 2000000.0
    max_ignition_delay_s: StrictFloat = 0.02

    @model_validator(mode="after")
    def validate_values(self) -> "HcciDieselCombustionConfig":
        has_duration_s = self.duration_s is not None
        has_duration_ms = self.duration_ms is not None
        if has_duration_s == has_duration_ms:
            raise ValueError("Use exactly one of duration_s or duration_ms for hcci_diesel")
        duration_s = float(self.duration_s) if has_duration_s else float(self.duration_ms) * 1.0e-3
        if duration_s <= 0.0:
            raise ValueError("duration_s/duration_ms must resolve to > 0")
        if self.a <= 0.0:
            raise ValueError("a must be > 0")
        if self.m < 0.0:
            raise ValueError("m must be >= 0")
        if self.lambda_target <= 0.0:
            raise ValueError("lambda_target must be > 0")
        if self.lhv_J_per_kg <= 0.0:
            raise ValueError("lhv_J_per_kg must be > 0")
        if self.afr_stoich_kg_air_per_kg_fuel <= 0.0:
            raise ValueError("afr_stoich_kg_air_per_kg_fuel must be > 0")
        if not (0.0 < self.combustion_efficiency_0to1 <= 1.0):
            raise ValueError("combustion_efficiency_0to1 must be > 0 and <= 1")
        if self.slot_open_threshold_m2 < 0.0 or self.slot_closed_threshold_m2 < 0.0:
            raise ValueError("slot thresholds must be >= 0")
        if self.slot_closed_threshold_m2 > self.slot_open_threshold_m2:
            raise ValueError("slot_closed_threshold_m2 must be <= slot_open_threshold_m2")
        if self.compression_velocity_threshold_m_per_s < 0.0:
            raise ValueError("compression_velocity_threshold_m_per_s must be >= 0")
        if self.tau_A_s <= 0.0:
            raise ValueError("tau_A_s must be > 0")
        if self.tau_pressure_exponent < 0.0:
            raise ValueError("tau_pressure_exponent must be >= 0")
        if self.tau_activation_temperature_K <= 0.0:
            raise ValueError("tau_activation_temperature_K must be > 0")
        if self.tau_activation_energy_J_per_kg is not None and self.tau_activation_energy_J_per_kg <= 0.0:
            raise ValueError("tau_activation_energy_J_per_kg must be > 0 when provided")
        if self.tau_reference_pressure_Pa <= 0.0:
            raise ValueError("tau_reference_pressure_Pa must be > 0")
        if self.tau_reference_lambda <= 0.0:
            raise ValueError("tau_reference_lambda must be > 0")
        if self.lambda_slowdown_exponent < 0.0:
            raise ValueError("lambda_slowdown_exponent must be >= 0")
        if self.residual_slowdown_factor < 1.0:
            raise ValueError("residual_slowdown_factor must be >= 1")
        if self.beck_c1_s <= 0.0:
            raise ValueError("beck_c1_s must be > 0")
        if self.beck_reference_pressure_bar <= 0.0:
            raise ValueError("beck_reference_pressure_bar must be > 0")
        if self.beck_reference_o2_percent <= 0.0:
            raise ValueError("beck_reference_o2_percent must be > 0")
        if self.beck_cf_fuel_name not in BECK_COOL_FLAME_FUEL_NAMES:
            raise ValueError("beck_cf_fuel_name must be one of: " + ", ".join(BECK_COOL_FLAME_FUEL_NAMES))
        if not (0.0 < self.cool_flame_energy_fraction < 1.0):
            raise ValueError("cool_flame_energy_fraction must be > 0 and < 1")
        if self.cool_flame_duration_ms <= 0.0:
            raise ValueError("cool_flame_duration_ms must be > 0")
        if self.cool_flame_a <= 0.0:
            raise ValueError("cool_flame_a must be > 0")
        if self.cool_flame_m < 0.0:
            raise ValueError("cool_flame_m must be >= 0")
        if self.start_temperature_min_K <= 0.0:
            raise ValueError("start_temperature_min_K must be > 0")
        if self.start_pressure_min_Pa <= 0.0:
            raise ValueError("start_pressure_min_Pa must be > 0")
        if self.max_ignition_delay_s <= 0.0:
            raise ValueError("max_ignition_delay_s must be > 0")
        return self


class SimpleEvaporationConfig(StrictBaseModel):
    model: Literal["simple"]
    start_deg: StrictFloat
    duration_deg: StrictFloat
    evaporated_mass_per_cycle_kg: StrictFloat
    latent_heat_J_per_kg: StrictFloat
    angle_reference: Literal["absolute", "compression_tdc", "gas_exchange_tdc"]


WallHeatConfig = Annotated[Union[DisabledSubmodelConfig, WoschniHeatTransferConfig], Field(discriminator="model")]
WallTemperatureConfig = Annotated[Union[DisabledWallTemperatureConfig, CycleAverageWallTemperatureConfig], Field(discriminator="model")]
CombustionConfig = Annotated[Union[DisabledCombustionConfig, VibeCombustionConfig, HcciDieselCombustionConfig], Field(discriminator="model")]
EvaporationConfig = Annotated[Union[DisabledEvaporationConfig, SimpleEvaporationConfig], Field(discriminator="model")]


class SubmodelLibraryConfig(StrictBaseModel):
    volumes: dict[StrictStr, dict[StrictStr, object]] = Field(default_factory=dict)
    wall_heat: dict[StrictStr, dict[StrictStr, object]] = Field(default_factory=dict)
    wall_temperature: dict[StrictStr, dict[StrictStr, object]] = Field(default_factory=dict)
    combustion: dict[StrictStr, dict[StrictStr, object]] = Field(default_factory=dict)
    connections: dict[StrictStr, dict[StrictStr, object]] = Field(default_factory=dict)


class CrankSliderKinematicsConfig(StrictBaseModel):
    type: Literal["crank_slider"]
    bore_m: StrictFloat
    stroke_m: StrictFloat
    conrod_m: StrictFloat
    compression_ratio: StrictFloat
    phase_deg: StrictFloat


class CylinderVolumeConfig(StrictBaseModel):
    name: StrictStr
    type: Literal["cylinder"]
    initial_pressure_Pa: StrictFloat | None = None
    initial_mass_kg: StrictFloat | None = None
    initial_temperature_K: StrictFloat
    initial_burned_fraction_0to1: StrictFloat = 0.0
    initial_burned_mass_percent: StrictFloat | None = None
    kinematics: CrankSliderKinematicsConfig
    wall_heat: WallHeatConfig
    wall_temperature: WallTemperatureConfig = Field(default_factory=lambda: DisabledWallTemperatureConfig(model="none"))
    combustion: CombustionConfig
    evaporation: EvaporationConfig

    @model_validator(mode="after")
    def validate_initial_state(self) -> "CylinderVolumeConfig":
        if self.initial_temperature_K <= 0.0:
            raise ValueError("initial_temperature_K must be > 0")
        if self.initial_pressure_Pa is None and self.initial_mass_kg is None:
            raise ValueError("Either initial_pressure_Pa or initial_mass_kg must be provided")
        if self.initial_pressure_Pa is not None and self.initial_pressure_Pa <= 0.0:
            raise ValueError("initial_pressure_Pa must be > 0")
        if self.initial_mass_kg is not None and self.initial_mass_kg <= 0.0:
            raise ValueError("initial_mass_kg must be > 0")
        if self.initial_burned_fraction_0to1 < 0.0 or self.initial_burned_fraction_0to1 > 1.0:
            raise ValueError("initial_burned_fraction_0to1 must satisfy 0 <= x <= 1")
        if self.initial_burned_mass_percent is not None and (self.initial_burned_mass_percent < 0.0 or self.initial_burned_mass_percent > 100.0):
            raise ValueError("initial_burned_mass_percent must satisfy 0 <= x <= 100")
        return self

    @property
    def resolved_initial_burned_fraction_0to1(self) -> float:
        if self.initial_burned_mass_percent is not None:
            return float(self.initial_burned_mass_percent) / 100.0
        return float(self.initial_burned_fraction_0to1)


class PlenumVolumeConfig(StrictBaseModel):
    name: StrictStr
    type: Literal["plenum"]
    initial_pressure_Pa: StrictFloat | None = None
    initial_mass_kg: StrictFloat | None = None
    initial_temperature_K: StrictFloat
    initial_burned_fraction_0to1: StrictFloat = 0.0
    initial_burned_mass_percent: StrictFloat | None = None
    fixed_volume_m3: StrictFloat
    wall_heat: WallHeatConfig
    wall_temperature: WallTemperatureConfig = Field(default_factory=lambda: DisabledWallTemperatureConfig(model="none"))
    combustion: CombustionConfig
    evaporation: EvaporationConfig

    @model_validator(mode="after")
    def validate_initial_state(self) -> "PlenumVolumeConfig":
        if self.initial_temperature_K <= 0.0:
            raise ValueError("initial_temperature_K must be > 0")
        if self.initial_pressure_Pa is None and self.initial_mass_kg is None:
            raise ValueError("Either initial_pressure_Pa or initial_mass_kg must be provided")
        if self.initial_pressure_Pa is not None and self.initial_pressure_Pa <= 0.0:
            raise ValueError("initial_pressure_Pa must be > 0")
        if self.initial_mass_kg is not None and self.initial_mass_kg <= 0.0:
            raise ValueError("initial_mass_kg must be > 0")
        if self.initial_burned_fraction_0to1 < 0.0 or self.initial_burned_fraction_0to1 > 1.0:
            raise ValueError("initial_burned_fraction_0to1 must satisfy 0 <= x <= 1")
        if self.initial_burned_mass_percent is not None and (self.initial_burned_mass_percent < 0.0 or self.initial_burned_mass_percent > 100.0):
            raise ValueError("initial_burned_mass_percent must satisfy 0 <= x <= 100")
        return self

    @property
    def resolved_initial_burned_fraction_0to1(self) -> float:
        if self.initial_burned_mass_percent is not None:
            return float(self.initial_burned_mass_percent) / 100.0
        return float(self.initial_burned_fraction_0to1)


class BounceChamberVolumeConfig(StrictBaseModel):
    name: StrictStr
    type: Literal["bounce_chamber"]
    model: Literal["gas_spring", "gas_exchange"] = "gas_spring"
    initial_pressure_Pa: StrictFloat
    initial_temperature_K: StrictFloat
    initial_burned_fraction_0to1: StrictFloat = 0.0
    initial_burned_mass_percent: StrictFloat | None = None
    chamber_diameter_m: StrictFloat | None = None
    chamber_length_m: StrictFloat | None = None
    compression_ratio: StrictFloat | None = None
    chamber_volume0_m3: StrictFloat | None = None
    p0_Pa: StrictFloat | None = None
    polytropic_exponent: StrictFloat

    @property
    def derived_geometric_area_m2(self) -> float:
        diameter_m = float(self.chamber_diameter_m)
        return float(0.25 * math.pi * diameter_m * diameter_m)

    @property
    def derived_swept_volume_m3(self) -> float:
        area_m2 = self.derived_geometric_area_m2
        length_m = float(self.chamber_length_m)
        return float(area_m2 * length_m)

    @property
    def derived_chamber_volume0_m3(self) -> float:
        if self.chamber_volume0_m3 is not None:
            return float(self.chamber_volume0_m3)
        swept_m3 = self.derived_swept_volume_m3
        cr = float(self.compression_ratio)
        return float(swept_m3 * cr / (cr - 1.0))

    @property
    def derived_chamber_min_volume_m3(self) -> float:
        if self.chamber_volume0_m3 is not None:
            raise ValueError('legacy chamber_volume0_m3 does not uniquely define bounce minimum volume; resolve it in the builder with mechanics information')
        swept_m3 = self.derived_swept_volume_m3
        cr = float(self.compression_ratio)
        return float(swept_m3 / (cr - 1.0))

    @model_validator(mode="after")
    def validate_values(self) -> "BounceChamberVolumeConfig":
        has_new_geom = self.chamber_diameter_m is not None or self.chamber_length_m is not None or self.compression_ratio is not None
        has_old = self.chamber_volume0_m3 is not None

        if has_new_geom and has_old:
            raise ValueError('Use either chamber_diameter_m + chamber_length_m + compression_ratio or chamber_volume0_m3 (legacy Vmax at OT), not both')
        if not has_new_geom and not has_old:
            raise ValueError('bounce_chamber requires chamber_diameter_m + chamber_length_m + compression_ratio')

        if has_new_geom:
            if self.chamber_diameter_m is None or self.chamber_length_m is None or self.compression_ratio is None:
                raise ValueError('chamber_diameter_m, chamber_length_m and compression_ratio must be provided together')
            if self.chamber_diameter_m <= 0.0:
                raise ValueError('chamber_diameter_m must be > 0')
            if self.chamber_length_m <= 0.0:
                raise ValueError('chamber_length_m must be > 0')
            if self.compression_ratio <= 1.0:
                raise ValueError('bounce compression_ratio must be > 1')
        else:
            if self.chamber_volume0_m3 is None or self.chamber_volume0_m3 <= 0.0:
                raise ValueError('chamber_volume0_m3 must be > 0')

        if self.initial_pressure_Pa <= 0.0:
            raise ValueError('initial_pressure_Pa must be > 0')
        if self.initial_temperature_K <= 0.0:
            raise ValueError('initial_temperature_K must be > 0')
        if self.initial_burned_fraction_0to1 < 0.0 or self.initial_burned_fraction_0to1 > 1.0:
            raise ValueError("initial_burned_fraction_0to1 must satisfy 0 <= x <= 1")
        if self.initial_burned_mass_percent is not None and (self.initial_burned_mass_percent < 0.0 or self.initial_burned_mass_percent > 100.0):
            raise ValueError("initial_burned_mass_percent must satisfy 0 <= x <= 100")
        if self.p0_Pa is not None and self.p0_Pa <= 0.0:
            raise ValueError('p0_Pa must be > 0')
        if self.polytropic_exponent <= 0.0:
            raise ValueError('polytropic_exponent must be > 0')
        return self

    @property
    def resolved_initial_burned_fraction_0to1(self) -> float:
        if self.initial_burned_mass_percent is not None:
            return float(self.initial_burned_mass_percent) / 100.0
        return float(self.initial_burned_fraction_0to1)


class EnvironmentVolumeConfig(StrictBaseModel):
    name: StrictStr
    type: Literal["environment"]
    pressure_Pa: StrictFloat
    temperature_K: StrictFloat

    @model_validator(mode="after")
    def validate_state(self) -> "EnvironmentVolumeConfig":
        if self.pressure_Pa <= 0.0:
            raise ValueError("pressure_Pa must be > 0")
        if self.temperature_K <= 0.0:
            raise ValueError("temperature_K must be > 0")
        return self


VolumeConfig = Annotated[Union[CylinderVolumeConfig, PlenumVolumeConfig, BounceChamberVolumeConfig, EnvironmentVolumeConfig], Field(discriminator="type")]


class ConstantDischargeCoefficientsConfig(StrictBaseModel):
    mode: Literal["constant"]
    forward_cd: StrictFloat
    reverse_cd: StrictFloat


class TableDischargeCoefficientsConfig(StrictBaseModel):
    mode: Literal["table"]
    table_file: StrictStr


DischargeCoeffConfig = Annotated[
    Union[ConstantDischargeCoefficientsConfig, TableDischargeCoefficientsConfig],
    Field(discriminator="mode"),
]


class ValveConnectionConfig(StrictBaseModel):
    name: StrictStr
    type: Literal["valve"]
    from_volume: StrictStr
    to_volume: StrictStr
    opening_angle_deg: StrictFloat
    opening_reference: Literal["absolute", "compression_tdc", "gas_exchange_tdc"]
    profile_angle_domain: Literal["crank", "cam"]
    lift_scale: StrictFloat
    lash_m: StrictFloat
    lift_file: StrictStr
    alpha_k_file: StrictStr


class SlotConnectionConfig(StrictBaseModel):
    name: StrictStr
    type: Literal["slot"]
    from_volume: StrictStr
    to_volume: StrictStr
    source_of_data: Literal["rectangle"]
    opening_mode: Literal["by_distance", "by_angle"]
    distance_from_tdc_m: StrictFloat | None = None
    distance_from_tdc_mm: StrictFloat | None = None
    opening_angle_deg: StrictFloat | None = None
    piston_height_if_crankcase_m: StrictFloat
    entrance_angle_deg: StrictFloat
    width_m: StrictFloat | None = None
    width_mm: StrictFloat | None = None
    height_m: StrictFloat | None = None
    height_mm: StrictFloat | None = None
    open_fillet_radius_m: StrictFloat
    full_fillet_radius_m: StrictFloat
    number_of_identical_holes: StrictInt
    discharge_coefficients: DischargeCoeffConfig

    @property
    def resolved_distance_from_tdc_m(self) -> float | None:
        return _resolve_optional_length_m(
            self.distance_from_tdc_m,
            self.distance_from_tdc_mm,
            field_m="distance_from_tdc_m",
            field_mm="distance_from_tdc_mm",
            required=self.opening_mode == "by_distance",
            strictly_positive=False,
        )

    @property
    def resolved_width_m(self) -> float:
        return float(_resolve_optional_length_m(
            self.width_m,
            self.width_mm,
            field_m="width_m",
            field_mm="width_mm",
            required=True,
            strictly_positive=True,
        ))

    @property
    def resolved_height_m(self) -> float:
        return float(_resolve_optional_length_m(
            self.height_m,
            self.height_mm,
            field_m="height_m",
            field_mm="height_mm",
            required=True,
            strictly_positive=True,
        ))

    @model_validator(mode="after")
    def validate_opening(self) -> "SlotConnectionConfig":
        _ = self.resolved_width_m
        _ = self.resolved_height_m
        if self.opening_mode == "by_distance":
            if self.opening_angle_deg is not None:
                raise ValueError("by_distance requires opening_angle_deg to be null")
            _ = self.resolved_distance_from_tdc_m
        if self.opening_mode == "by_angle":
            if self.opening_angle_deg is None:
                raise ValueError("by_angle requires opening_angle_deg")
            if self.distance_from_tdc_m is not None or self.distance_from_tdc_mm is not None:
                raise ValueError("by_angle requires distance_from_tdc_m and distance_from_tdc_mm to be null")
        return self


class OrificeConnectionConfig(StrictBaseModel):
    name: StrictStr
    type: Literal["orifice"]
    from_volume: StrictStr
    to_volume: StrictStr
    area_m2: StrictFloat | None = None
    diameter_mm: StrictFloat | None = None
    forward_cd: StrictFloat
    reverse_cd: StrictFloat

    @property
    def resolved_area_m2(self) -> float:
        return _resolve_area_m2(self.area_m2, self.diameter_mm)

    @model_validator(mode="after")
    def validate_orifice(self) -> "OrificeConnectionConfig":
        _ = self.resolved_area_m2
        if self.forward_cd < 0.0 or self.reverse_cd < 0.0:
            raise ValueError("forward_cd and reverse_cd must be >= 0")
        return self


class CheckValveConnectionConfig(StrictBaseModel):
    name: StrictStr
    type: Literal["check_valve"]
    from_volume: StrictStr
    to_volume: StrictStr
    area_m2: StrictFloat | None = None
    diameter_mm: StrictFloat | None = None
    discharge_coefficient: StrictFloat
    cracking_pressure_Pa: StrictFloat = 0.0

    @property
    def resolved_area_m2(self) -> float:
        return _resolve_area_m2(self.area_m2, self.diameter_mm)

    @model_validator(mode="after")
    def validate_check_valve(self) -> "CheckValveConnectionConfig":
        _ = self.resolved_area_m2
        if self.discharge_coefficient < 0.0:
            raise ValueError("discharge_coefficient must be >= 0")
        if self.cracking_pressure_Pa < 0.0:
            raise ValueError("cracking_pressure_Pa must be >= 0")
        return self


ConnectionConfig = Annotated[Union[ValveConnectionConfig, SlotConnectionConfig, OrificeConnectionConfig, CheckValveConnectionConfig], Field(discriminator="type")]



class FreePistonFluidStateConfig(StrictBaseModel):
    pressure_Pa: StrictFloat
    temperature_K: StrictFloat

    @model_validator(mode="after")
    def validate_values(self) -> "FreePistonFluidStateConfig":
        if self.pressure_Pa <= 0.0:
            raise ValueError("pressure_Pa must be > 0")
        if self.temperature_K <= 0.0:
            raise ValueError("temperature_K must be > 0")
        return self


class FreePistonCombustionStateConfig(StrictBaseModel):
    burned_fraction_0to1: StrictFloat = 0.0
    burned_mass_percent: StrictFloat | None = None
    released_energy_J: StrictFloat = 0.0
    ignition_armed: StrictBool = False
    injection_armed: StrictBool = False

    @property
    def resolved_burned_fraction_0to1(self) -> float:
        if self.burned_mass_percent is not None:
            return float(self.burned_mass_percent) / 100.0
        return float(self.burned_fraction_0to1)

    @model_validator(mode="after")
    def validate_values(self) -> "FreePistonCombustionStateConfig":
        if self.burned_fraction_0to1 < 0.0 or self.burned_fraction_0to1 > 1.0:
            raise ValueError("burned_fraction_0to1 must satisfy 0 <= x <= 1")
        if self.burned_mass_percent is not None and (self.burned_mass_percent < 0.0 or self.burned_mass_percent > 100.0):
            raise ValueError("burned_mass_percent must satisfy 0 <= x <= 100")
        return self


class FreePistonInitialConditionsConfig(StrictBaseModel):
    x0_m: StrictFloat
    v0_m_per_s: StrictFloat
    cylinder: FreePistonFluidStateConfig | None = None
    bounce: FreePistonFluidStateConfig | None = None
    combustion_state: FreePistonCombustionStateConfig = Field(default_factory=FreePistonCombustionStateConfig)


class FreePistonMechanicsConfig(StrictBaseModel):
    kinematics_type: Literal["linear", "oscillating_rotary"] = "linear"
    moving_mass_kg: StrictFloat
    piston_diameter_m: StrictFloat | None = None
    compression_ratio: StrictFloat | None = None
    piston_area_m2: StrictFloat | None = None
    clearance_volume_m3: StrictFloat | None = None
    x_min_m: StrictFloat
    x_max_m: StrictFloat
    angle_min_deg: StrictFloat | None = None
    angle_max_deg: StrictFloat | None = None
    effective_radius_m: StrictFloat | None = None
    rotary_inertia_kg_m2: StrictFloat | None = None

    @property
    def nominal_stroke_m(self) -> float:
        return float(self.x_max_m - self.x_min_m)

    @property
    def derived_piston_area_m2(self) -> float:
        if self.piston_area_m2 is not None:
            return float(self.piston_area_m2)
        diameter_m = float(self.piston_diameter_m)
        return float(0.25 * math.pi * diameter_m * diameter_m)

    @property
    def derived_clearance_volume_m3(self) -> float:
        if self.clearance_volume_m3 is not None:
            return float(self.clearance_volume_m3)
        swept_volume_m3 = self.derived_piston_area_m2 * self.nominal_stroke_m
        cr = float(self.compression_ratio)
        return float(swept_volume_m3 / (cr - 1.0))

    @property
    def derived_piston_diameter_m(self) -> float:
        if self.piston_diameter_m is not None:
            return float(self.piston_diameter_m)
        return float(math.sqrt(4.0 * float(self.piston_area_m2) / math.pi))

    @property
    def derived_compression_ratio(self) -> float:
        if self.compression_ratio is not None:
            return float(self.compression_ratio)
        swept_volume_m3 = self.derived_piston_area_m2 * self.nominal_stroke_m
        clearance_volume_m3 = float(self.clearance_volume_m3)
        return float((swept_volume_m3 + clearance_volume_m3) / clearance_volume_m3)

    @model_validator(mode="after")
    def validate_values(self) -> "FreePistonMechanicsConfig":
        if self.moving_mass_kg <= 0.0:
            raise ValueError("moving_mass_kg must be > 0")
        if self.x_max_m <= self.x_min_m:
            raise ValueError("x_max_m must be > x_min_m")
        if self.kinematics_type == "oscillating_rotary":
            if self.angle_min_deg is None or self.angle_max_deg is None:
                raise ValueError("oscillating_rotary requires angle_min_deg and angle_max_deg")
            if self.angle_max_deg <= self.angle_min_deg:
                raise ValueError("angle_max_deg must be > angle_min_deg for oscillating_rotary")
            if self.effective_radius_m is None or self.effective_radius_m <= 0.0:
                raise ValueError("oscillating_rotary requires effective_radius_m > 0")
            if self.rotary_inertia_kg_m2 is None or self.rotary_inertia_kg_m2 <= 0.0:
                raise ValueError("oscillating_rotary requires rotary_inertia_kg_m2 > 0")

        has_new = self.piston_diameter_m is not None or self.compression_ratio is not None
        has_old = self.piston_area_m2 is not None or self.clearance_volume_m3 is not None

        if has_new and has_old:
            raise ValueError("Use either piston_diameter_m + compression_ratio or piston_area_m2 + clearance_volume_m3, not both")
        if not has_new and not has_old:
            raise ValueError("Free-piston mechanics require piston_diameter_m + compression_ratio")

        if has_new:
            if self.piston_diameter_m is None or self.compression_ratio is None:
                raise ValueError("piston_diameter_m and compression_ratio must be provided together")
            if self.piston_diameter_m <= 0.0:
                raise ValueError("piston_diameter_m must be > 0")
            if self.compression_ratio <= 1.0:
                raise ValueError("compression_ratio must be > 1")
        else:
            if self.piston_area_m2 is None or self.clearance_volume_m3 is None:
                raise ValueError("piston_area_m2 and clearance_volume_m3 must be provided together")
            if self.piston_area_m2 <= 0.0:
                raise ValueError("piston_area_m2 must be > 0")
            if self.clearance_volume_m3 <= 0.0:
                raise ValueError("clearance_volume_m3 must be > 0")

        return self


class FreePistonFrictionConfig(StrictBaseModel):
    model: Literal["coulomb_viscous"]
    fc_N: StrictFloat
    cv_Ns_per_m: StrictFloat

    @model_validator(mode="after")
    def validate_values(self) -> "FreePistonFrictionConfig":
        if self.fc_N < 0.0:
            raise ValueError("fc_N must be >= 0")
        if self.cv_Ns_per_m < 0.0:
            raise ValueError("cv_Ns_per_m must be >= 0")
        return self


class FreePistonLoadConfig(StrictBaseModel):
    model: Literal["none", "viscous", "electromagnetic_linear", "generator_controlled", "linear_generator_regulated"]
    damping_Ns_per_m: StrictFloat
    max_damping_Ns_per_m: StrictFloat | None = None
    control_zone_m: StrictFloat | None = None
    power_target_W: StrictFloat | None = None
    efficiency_0to1: StrictFloat | None = None
    min_velocity_m_per_s: StrictFloat | None = None
    assist_velocity_threshold_m_per_s: StrictFloat | None = None
    assist_force_N: StrictFloat | None = None
    target_margin_m: StrictFloat | None = None
    hard_margin_m: StrictFloat | None = None
    stop_kp: StrictFloat | None = None
    max_force_N: StrictFloat | None = None

    @model_validator(mode="after")
    def validate_values(self) -> "FreePistonLoadConfig":
        if self.damping_Ns_per_m < 0.0:
            raise ValueError("damping_Ns_per_m must be >= 0")
        if self.max_damping_Ns_per_m is not None and self.max_damping_Ns_per_m < 0.0:
            raise ValueError("max_damping_Ns_per_m must be >= 0")
        if self.control_zone_m is not None and self.control_zone_m < 0.0:
            raise ValueError("control_zone_m must be >= 0")
        if self.power_target_W is not None and self.power_target_W < 0.0:
            raise ValueError("power_target_W must be >= 0")
        if self.efficiency_0to1 is not None and not (0.0 < self.efficiency_0to1 <= 1.0):
            raise ValueError("efficiency_0to1 must be > 0 and <= 1")
        if self.min_velocity_m_per_s is not None and self.min_velocity_m_per_s <= 0.0:
            raise ValueError("min_velocity_m_per_s must be > 0")
        if self.assist_velocity_threshold_m_per_s is not None and self.assist_velocity_threshold_m_per_s <= 0.0:
            raise ValueError("assist_velocity_threshold_m_per_s must be > 0")
        if self.assist_force_N is not None and self.assist_force_N < 0.0:
            raise ValueError("assist_force_N must be >= 0")
        if self.target_margin_m is not None and self.target_margin_m < 0.0:
            raise ValueError("target_margin_m must be >= 0")
        if self.hard_margin_m is not None and self.hard_margin_m < 0.0:
            raise ValueError("hard_margin_m must be >= 0")
        if self.stop_kp is not None and self.stop_kp < 0.0:
            raise ValueError("stop_kp must be >= 0")
        if self.max_force_N is not None and self.max_force_N <= 0.0:
            raise ValueError("max_force_N must be > 0")
        if self.model == "generator_controlled":
            if self.max_damping_Ns_per_m is None:
                raise ValueError("generator_controlled requires max_damping_Ns_per_m")
            if self.max_damping_Ns_per_m < self.damping_Ns_per_m:
                raise ValueError("max_damping_Ns_per_m must be >= damping_Ns_per_m")
            if self.control_zone_m is None or self.control_zone_m <= 0.0:
                raise ValueError("generator_controlled requires control_zone_m > 0")
        if self.model == "linear_generator_regulated":
            if self.max_damping_Ns_per_m is None or self.max_damping_Ns_per_m <= 0.0:
                raise ValueError("linear_generator_regulated requires max_damping_Ns_per_m > 0")
            if self.max_damping_Ns_per_m < self.damping_Ns_per_m:
                raise ValueError("max_damping_Ns_per_m must be >= damping_Ns_per_m")
            if self.control_zone_m is None or self.control_zone_m <= 0.0:
                raise ValueError("linear_generator_regulated requires control_zone_m > 0")
            if self.power_target_W is None or self.power_target_W < 0.0:
                raise ValueError("linear_generator_regulated requires power_target_W >= 0")
            if self.efficiency_0to1 is None or not (0.0 < self.efficiency_0to1 <= 1.0):
                raise ValueError("linear_generator_regulated requires efficiency_0to1 in (0, 1]")
            if self.min_velocity_m_per_s is None or self.min_velocity_m_per_s <= 0.0:
                raise ValueError("linear_generator_regulated requires min_velocity_m_per_s > 0")
            if self.target_margin_m is None or self.target_margin_m < 0.0:
                raise ValueError("linear_generator_regulated requires target_margin_m >= 0")
            if self.hard_margin_m is None or self.hard_margin_m < 0.0:
                raise ValueError("linear_generator_regulated requires hard_margin_m >= 0")
            if self.target_margin_m is not None and self.hard_margin_m is not None and self.target_margin_m < self.hard_margin_m:
                raise ValueError("target_margin_m must be >= hard_margin_m")
            if self.control_zone_m is not None and self.target_margin_m is not None and self.control_zone_m <= self.target_margin_m:
                raise ValueError("control_zone_m must be > target_margin_m")
            if self.stop_kp is None or self.stop_kp <= 0.0:
                raise ValueError("linear_generator_regulated requires stop_kp > 0")
        return self


class FreePistonScavengingConfig(StrictBaseModel):
    enabled: StrictBool = False
    model: Literal["overlap_short_circuit_0d"] = "overlap_short_circuit_0d"
    scavenging_factor: StrictFloat = 1.25
    max_trapping_efficiency: StrictFloat = 0.92
    short_circuit_start_ratio: StrictFloat = 0.70
    short_circuit_slope: StrictFloat = 0.35
    max_short_circuit_fraction: StrictFloat = 0.35
    min_residual_fraction: StrictFloat = 0.03

    @model_validator(mode="after")
    def validate_values(self) -> "FreePistonScavengingConfig":
        if self.scavenging_factor < 0.0:
            raise ValueError("scavenging_factor must be >= 0")
        if not (0.0 <= self.max_trapping_efficiency <= 1.0):
            raise ValueError("max_trapping_efficiency must satisfy 0 <= x <= 1")
        if self.short_circuit_start_ratio < 0.0:
            raise ValueError("short_circuit_start_ratio must be >= 0")
        if self.short_circuit_slope <= 0.0:
            raise ValueError("short_circuit_slope must be > 0")
        if not (0.0 <= self.max_short_circuit_fraction <= 1.0):
            raise ValueError("max_short_circuit_fraction must satisfy 0 <= x <= 1")
        if not (0.0 <= self.min_residual_fraction <= 1.0):
            raise ValueError("min_residual_fraction must satisfy 0 <= x <= 1")
        return self


class FreePistonBounceConfig(StrictBaseModel):
    model: Literal["gas_spring"]
    chamber_diameter_m: StrictFloat | None = None
    chamber_length_m: StrictFloat | None = None
    compression_ratio: StrictFloat | None = None
    chamber_volume0_m3: StrictFloat | None = None
    p0_Pa: StrictFloat | None = None
    polytropic_exponent: StrictFloat

    @property
    def derived_geometric_area_m2(self) -> float:
        diameter_m = float(self.chamber_diameter_m)
        return float(0.25 * math.pi * diameter_m * diameter_m)

    @property
    def derived_swept_volume_m3(self) -> float:
        area_m2 = self.derived_geometric_area_m2
        length_m = float(self.chamber_length_m)
        return float(area_m2 * length_m)

    @property
    def derived_chamber_volume0_m3(self) -> float:
        if self.chamber_volume0_m3 is not None:
            return float(self.chamber_volume0_m3)
        swept_m3 = self.derived_swept_volume_m3
        cr = float(self.compression_ratio)
        return float(swept_m3 * cr / (cr - 1.0))

    @property
    def derived_chamber_min_volume_m3(self) -> float:
        if self.chamber_volume0_m3 is not None:
            raise ValueError('legacy chamber_volume0_m3 does not uniquely define bounce minimum volume; resolve it in the builder with mechanics information')
        swept_m3 = self.derived_swept_volume_m3
        cr = float(self.compression_ratio)
        return float(swept_m3 / (cr - 1.0))

    @model_validator(mode="after")
    def validate_values(self) -> "FreePistonBounceConfig":
        has_new_geom = self.chamber_diameter_m is not None or self.chamber_length_m is not None or self.compression_ratio is not None
        has_old = self.chamber_volume0_m3 is not None

        if has_new_geom and has_old:
            raise ValueError('Use either chamber_diameter_m + chamber_length_m + compression_ratio or chamber_volume0_m3 (legacy Vmax at UT), not both')
        if not has_new_geom and not has_old:
            raise ValueError('Free-piston bounce requires chamber_diameter_m + chamber_length_m + compression_ratio')

        if has_new_geom:
            if self.chamber_diameter_m is None or self.chamber_length_m is None or self.compression_ratio is None:
                raise ValueError('chamber_diameter_m, chamber_length_m and compression_ratio must be provided together')
            if self.chamber_diameter_m <= 0.0:
                raise ValueError('chamber_diameter_m must be > 0')
            if self.chamber_length_m <= 0.0:
                raise ValueError('chamber_length_m must be > 0')
            if self.compression_ratio <= 1.0:
                raise ValueError('bounce compression_ratio must be > 1')
        else:
            if self.chamber_volume0_m3 is None or self.chamber_volume0_m3 <= 0.0:
                raise ValueError('chamber_volume0_m3 must be > 0')

        if self.p0_Pa is not None and self.p0_Pa <= 0.0:
            raise ValueError('p0_Pa must be > 0')
        if self.polytropic_exponent <= 0.0:
            raise ValueError('polytropic_exponent must be > 0')
        return self


class FreePistonConfig(StrictBaseModel):
    initial_conditions: FreePistonInitialConditionsConfig
    mechanics: FreePistonMechanicsConfig
    friction: FreePistonFrictionConfig
    load: FreePistonLoadConfig
    scavenging: FreePistonScavengingConfig = Field(default_factory=FreePistonScavengingConfig)
    bounce: FreePistonBounceConfig | None = None


class PreprocessingConfig(StrictBaseModel):
    gas_properties: GasPropertiesConfig
    features: FeatureToggleConfig
    engine: EngineConfig
    submodels: SubmodelLibraryConfig = Field(default_factory=SubmodelLibraryConfig)
    volumes: list[VolumeConfig]
    connections: list[ConnectionConfig]



class RootConfig(StrictBaseModel):
    test_description: StrictStr | None = None
    versioning: dict[str, object] | None = None
    modeling: ModelingConfig = Field(default_factory=ModelingConfig)
    preprocessing: PreprocessingConfig
    simulation: SimulationConfig
    postprocessing: PostprocessingConfig
    gasexchange: dict[str, object] | None = None
    free_piston: FreePistonConfig | None = None

    @model_validator(mode="after")
    def validate_topology(self) -> "RootConfig":
        names = [v.name for v in self.preprocessing.volumes]
        if len(names) != len(set(names)):
            raise ValueError("Volume names must be unique")
        known = set(names)
        conn_names = [c.name for c in self.preprocessing.connections]
        if len(conn_names) != len(set(conn_names)):
            raise ValueError("Connection names must be unique")
        for conn in self.preprocessing.connections:
            if conn.from_volume not in known or conn.to_volume not in known:
                raise ValueError(f"Connection {conn.name} references unknown volumes")
            if conn.from_volume == conn.to_volume:
                raise ValueError(f"Connection {conn.name} must connect distinct volumes")
        if self.postprocessing.sampling.mode == "time":
            if self.postprocessing.sampling.step_s < self.simulation.dt_s:
                raise ValueError("time-based output step must be >= dt_s")
        if self.modeling.architecture == "free_piston":
            if self.free_piston is None:
                raise ValueError("free_piston section is required when modeling.architecture = free_piston")
            cylinder_volumes = [vol for vol in self.preprocessing.volumes if isinstance(vol, CylinderVolumeConfig)]
            bounce_volumes = [vol for vol in self.preprocessing.volumes if isinstance(vol, BounceChamberVolumeConfig)]
            if len(cylinder_volumes) > 2:
                raise ValueError("free_piston architecture supports at most two cylinder volumes in preprocessing.volumes")
            if len(bounce_volumes) > 2:
                raise ValueError("free_piston architecture supports at most two bounce_chamber volumes in preprocessing.volumes")
            if self.preprocessing.connections and not cylinder_volumes:
                raise ValueError("free_piston architecture requires one explicit cylinder volume when preprocessing.connections are used")
            bounce_names = {vol.name for vol in bounce_volumes}
            bounce_models = {vol.name: str(vol.model) for vol in bounce_volumes}
            for conn in self.preprocessing.connections:
                if isinstance(conn, ValveConnectionConfig):
                    raise ValueError("free_piston coldflow currently supports only slot, orifice and check_valve preprocessing.connections")
                if isinstance(conn, SlotConnectionConfig) and conn.opening_mode != "by_distance":
                    raise ValueError("free_piston coldflow requires slot opening_mode = by_distance")
                if conn.from_volume in bounce_names or conn.to_volume in bounce_names:
                    bounce_name = conn.from_volume if conn.from_volume in bounce_names else conn.to_volume
                    bounce_model = bounce_models.get(bounce_name, 'gas_spring')
                    if bounce_model != 'gas_exchange':
                        raise ValueError("bounce_chamber is a closed mechanically coupled volume and must not be referenced by preprocessing.connections unless model = gas_exchange")
                    if not isinstance(conn, (OrificeConnectionConfig, CheckValveConnectionConfig)):
                        raise ValueError("Stage A gas_exchange bounce currently supports only orifice and check_valve preprocessing.connections to/from bounce_chamber")
            if not cylinder_volumes and self.free_piston.initial_conditions.cylinder is None:
                raise ValueError(
                    "free_piston architecture requires one cylinder volume with initial_pressure_Pa/initial_mass_kg "
                    "and initial_temperature_K in preprocessing.volumes"
                )
            if bounce_volumes:
                if self.free_piston.bounce is not None:
                    raise ValueError("When a bounce_chamber is defined in preprocessing.volumes, free_piston.bounce must be omitted")
                if self.free_piston.initial_conditions.bounce is not None:
                    raise ValueError("When a bounce_chamber is defined in preprocessing.volumes, free_piston.initial_conditions.bounce must be omitted")
            elif self.free_piston.bounce is None:
                raise ValueError("free_piston requires either preprocessing.volumes[type=bounce_chamber] or free_piston.bounce")
            if not (self.free_piston.mechanics.x_min_m <= self.free_piston.initial_conditions.x0_m <= self.free_piston.mechanics.x_max_m):
                raise ValueError("free_piston.initial_conditions.x0_m must lie within mechanics.x_min_m .. mechanics.x_max_m")
        return self

    @property
    def gas_properties(self) -> GasPropertiesConfig:
        return self.preprocessing.gas_properties

    @property
    def features(self) -> FeatureToggleConfig:
        return self.preprocessing.features

    @property
    def engine(self) -> EngineConfig:
        return self.preprocessing.engine

    @property
    def volumes(self) -> list[VolumeConfig]:
        return self.preprocessing.volumes

    @property
    def connections(self) -> list[ConnectionConfig]:
        return self.preprocessing.connections


class ConfigLoader:
    @staticmethod
    def load(path: str | Path) -> RootConfig:
        from thermo0d.input.config_loader import ConfigLoader as InputConfigLoader
        return InputConfigLoader.load(path)


def load_config(path: str | Path) -> RootConfig:
    from thermo0d.input.config_loader import load_config as input_load_config
    return input_load_config(path)
