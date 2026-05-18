from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import yaml

from thermo0d.config.constants import KinCol, KinematicsType
from thermo0d.config.models import load_config
from thermo0d.input.model_builder import MatrixModelBuilder
from thermo0d.physics.kinematics import cylinder_volume_and_dvdt


def _minimal_config(initial_key: str, initial_value: float) -> dict:
    return {
        'test_description': 'initial state test',
        'preprocessing': {
            'gas_properties': {'cp_J_per_kgK': 1005.0, 'cv_J_per_kgK': 718.0, 'R_J_per_kgK': 287.0},
            'features': {'mass_flow': True, 'wall_heat': False, 'combustion': False, 'evaporation': False, 'pv_work': True},
            'engine': {'cycle_type': '4t', 'speed_rpm': 2500.0},
            'volumes': [
                {
                    'name': 'cylinder',
                    'type': 'cylinder',
                    initial_key: initial_value,
                    'initial_temperature_K': 360.0,
                    'kinematics': {
                        'type': 'crank_slider',
                        'bore_m': 0.086,
                        'stroke_m': 0.086,
                        'conrod_m': 0.143,
                        'compression_ratio': 10.5,
                        'phase_deg': 0.0,
                    },
                    'wall_heat': {'model': 'none'},
                    'combustion': {'model': 'none'},
                    'evaporation': {'model': 'none'},
                },
                {
                    'name': 'intake_plenum',
                    'type': 'plenum',
                    'initial_pressure_Pa': 101325.0,
                    'initial_temperature_K': 300.0,
                    'fixed_volume_m3': 0.003,
                    'wall_heat': {'model': 'none'},
                    'combustion': {'model': 'none'},
                    'evaporation': {'model': 'none'},
                },
            ],
            'connections': [],
        },
        'simulation': {
            'dt_s': 2.0e-5,
            'total_cycles': 1,
            'save_last_cycles': 1,
            'solver': {'kind': 'rk4', 'rtol': 1.0e-6, 'atol': 1.0e-9},
        },
        'postprocessing': {
            'csv_path': 'results/test.csv',
            'csv_separator': ';',
            'sampling': {'mode': 'time', 'step_s': 2.0e-5},
        },
    }


def test_pressure_temperature_initial_state_is_converted_to_mass_for_cylinder(tmp_path: Path):
    cfg_path = tmp_path / 'pressure.yaml'
    yaml.safe_dump(_minimal_config('initial_pressure_Pa', 1080650.993791), cfg_path.open('w', encoding='utf-8'), sort_keys=False)
    cfg = load_config(cfg_path)
    cyl = cfg.preprocessing.volumes[0]
    assert cyl.initial_pressure_Pa is not None
    builder = MatrixModelBuilder(cfg, cfg_path)
    bundle = builder.build()

    kin_row = np.zeros((len(KinCol),), dtype=np.float64)
    kin_row[KinCol.TYPE] = float(KinematicsType.CRANK_SLIDER)
    kin_row[KinCol.BORE] = cyl.kinematics.bore_m
    kin_row[KinCol.STROKE] = cyl.kinematics.stroke_m
    kin_row[KinCol.CONROD] = cyl.kinematics.conrod_m
    kin_row[KinCol.COMPRESSION_RATIO] = cyl.kinematics.compression_ratio
    kin_row[KinCol.PHASE_DEG] = cyl.kinematics.phase_deg
    kin_row[KinCol.SPEED_RPM] = cfg.engine.speed_rpm
    kin_row[KinCol.CYCLE_DEG] = 720.0
    volume_m3, _, _ = cylinder_volume_and_dvdt(kin_row, 0.0)

    expected_mass = cyl.initial_pressure_Pa * volume_m3 / (cfg.gas_properties.R_J_per_kgK * cyl.initial_temperature_K)
    assert math.isclose(float(bundle.y_init[0]), float(expected_mass), rel_tol=1e-12, abs_tol=0.0)


def test_legacy_initial_mass_config_remains_loadable(tmp_path: Path):
    cfg_path = tmp_path / 'legacy_mass.yaml'
    yaml.safe_dump(_minimal_config('initial_mass_kg', 0.00055), cfg_path.open('w', encoding='utf-8'), sort_keys=False)

    cfg = load_config(cfg_path)
    builder = MatrixModelBuilder(cfg, cfg_path)
    bundle = builder.build()
    assert float(bundle.y_init[0]) > 0.0
