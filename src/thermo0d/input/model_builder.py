from __future__ import annotations

from pathlib import Path

import numpy as np

from thermo0d.config.constants import (
    AngleReference,
    CycleType,
    KinCol,
    KinematicsType,
    WoschniDpMode,
    WoschniPhaseMode,
    WoschniReferenceMode,
    WoschniVariant,
)
from thermo0d.config.models import BounceChamberVolumeConfig, CylinderVolumeConfig, EnvironmentVolumeConfig, PlenumVolumeConfig, RootConfig
from thermo0d.core.model_bundle import ModelBundle
from thermo0d.physics.kinematics import cylinder_volume_and_dvdt
from thermo0d.input.table_loading import load_numeric_table


class MatrixModelBuilder:
    def __init__(self, config: RootConfig, config_path: str | Path):
        self.config = config
        self.config_path = Path(config_path).resolve()
        self.config_dir = self.config_path.parent

    @staticmethod
    def _load_csv_table(path: Path, expected_cols: int, table_kind: str = "generic") -> np.ndarray:
        return load_numeric_table(path, expected_cols=expected_cols, table_kind=table_kind).data

    @staticmethod
    def _ref_enum(name: str) -> int:
        return {
            'absolute': AngleReference.ABSOLUTE,
            'compression_tdc': AngleReference.COMPRESSION_TDC,
            'gas_exchange_tdc': AngleReference.GAS_EXCHANGE_TDC,
        }[name]

    @staticmethod
    def _cycle_enum(name: str) -> CycleType:
        return CycleType.TWO_STROKE if name == '2t' else CycleType.FOUR_STROKE

    def _initial_volume_m3(self, vol: CylinderVolumeConfig | PlenumVolumeConfig | EnvironmentVolumeConfig) -> float:
        if isinstance(vol, PlenumVolumeConfig):
            return float(vol.fixed_volume_m3)
        if isinstance(vol, EnvironmentVolumeConfig):
            return 0.0
        cycle_type = self._cycle_enum(self.config.engine.cycle_type)
        cycle_deg = 360.0 if cycle_type == CycleType.TWO_STROKE else 720.0
        kin_row = np.zeros((len(KinCol),), dtype=np.float64)
        kin_row[KinCol.TYPE] = float(KinematicsType.CRANK_SLIDER)
        kin_row[KinCol.BORE] = vol.kinematics.bore_m
        kin_row[KinCol.STROKE] = vol.kinematics.stroke_m
        kin_row[KinCol.CONROD] = vol.kinematics.conrod_m
        kin_row[KinCol.COMPRESSION_RATIO] = vol.kinematics.compression_ratio
        kin_row[KinCol.PHASE_DEG] = vol.kinematics.phase_deg
        kin_row[KinCol.SPEED_RPM] = self.config.engine.speed_rpm
        kin_row[KinCol.CYCLE_DEG] = cycle_deg
        volume, _, _ = cylinder_volume_and_dvdt(kin_row, 0.0)
        return float(volume)

    @staticmethod
    def _woschni_variant_enum(name: str) -> int:
        return {"legacy": WoschniVariant.LEGACY, "promo": WoschniVariant.PROMO, "gt": WoschniVariant.GT, "classic": WoschniVariant.CLASSIC, "swirl": WoschniVariant.SWIRL, "huber": WoschniVariant.HUBER}[name]

    @staticmethod
    def _woschni_dp_mode_enum(name: str) -> int:
        return {"off": WoschniDpMode.OFF, "instant": WoschniDpMode.INSTANT, "motored": WoschniDpMode.MOTORED}[name]

    @staticmethod
    def _woschni_reference_mode_enum(name: str) -> int:
        return {"none": WoschniReferenceMode.NONE, "pre_combustion_latch": WoschniReferenceMode.PRE_COMBUSTION_LATCH, "cycle_start_latch": WoschniReferenceMode.CYCLE_START_LATCH}[name]

    @staticmethod
    def _woschni_phase_mode_enum(name: str) -> int:
        return {"legacy": WoschniPhaseMode.LEGACY, "promo": WoschniPhaseMode.PROMO, "classic": WoschniPhaseMode.CLASSIC, "gt": WoschniPhaseMode.GT}[name]

    @staticmethod
    def _cylinder_reference_volumes(vol: CylinderVolumeConfig) -> tuple[float, float]:
        bore = float(vol.kinematics.bore_m)
        stroke = float(vol.kinematics.stroke_m)
        cr = float(vol.kinematics.compression_ratio)
        swept = 0.25 * np.pi * bore * bore * stroke
        clearance = swept / max(cr - 1.0, 1.0e-12)
        return clearance, clearance + swept

    def _initial_mass_kg(self, vol: CylinderVolumeConfig | PlenumVolumeConfig | BounceChamberVolumeConfig | EnvironmentVolumeConfig) -> float:
        if isinstance(vol, EnvironmentVolumeConfig):
            return 0.0
        if vol.initial_pressure_Pa is not None:
            volume_m3 = self._initial_volume_m3(vol)
            return float(vol.initial_pressure_Pa * volume_m3 / (self.config.gas_properties.R_J_per_kgK * vol.initial_temperature_K))
        if vol.initial_mass_kg is None:
            raise ValueError(f"Volume {vol.name} is missing both initial_pressure_Pa and initial_mass_kg")
        return float(vol.initial_mass_kg)

    @staticmethod
    def _initial_burned_fraction_0to1(vol: CylinderVolumeConfig | PlenumVolumeConfig | BounceChamberVolumeConfig | EnvironmentVolumeConfig) -> float:
        if isinstance(vol, EnvironmentVolumeConfig):
            return 0.0
        if hasattr(vol, "resolved_initial_burned_fraction_0to1"):
            value = float(vol.resolved_initial_burned_fraction_0to1)
        elif getattr(vol, "initial_burned_mass_percent", None) is not None:
            value = float(vol.initial_burned_mass_percent) / 100.0
        else:
            value = float(getattr(vol, "initial_burned_fraction_0to1", 0.0) or 0.0)
        return min(max(value, 0.0), 1.0)

    def _build_conventional_bundle(self) -> ModelBundle:
        from thermo0d.model.conventional.builder import build_conventional_bundle
        return build_conventional_bundle(self)

    def _build_classic_bundle(self) -> ModelBundle:
        return self._build_conventional_bundle()

    def build(self) -> ModelBundle:
        architecture = getattr(getattr(self.config, 'modeling', None), 'architecture', 'classic')
        if architecture == 'free_piston':
            from thermo0d.model.free_piston.builder import build_free_piston_bundle
            return build_free_piston_bundle(self)
        return self._build_conventional_bundle()


def build_model_bundle(config: RootConfig, config_path: str | Path) -> ModelBundle:
    return MatrixModelBuilder(config, config_path).build()
