from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from thermo0d.config.constants import ConnCol, ConnectionType, VolumeCol, VolumeType
from thermo0d.config.models import RootConfig
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.output.rows import ResultRowBuilder
from thermo0d.physics.rhs import RHSWrapper


def _base_config_dict() -> dict:
    return {
        'test_description': 'environment-orifice-test',
        'preprocessing': {
            'gas_properties': {
                'cp_J_per_kgK': 1005.0,
                'cv_J_per_kgK': 718.0,
                'R_J_per_kgK': 287.0,
            },
            'features': {
                'mass_flow': True,
                'wall_heat': False,
                'combustion': False,
                'evaporation': False,
                'pv_work': False,
            },
            'engine': {
                'cycle_type': '4t',
                'speed_rpm': 3000.0,
            },
            'volumes': [
                {
                    'name': 'ambient',
                    'type': 'environment',
                    'pressure_Pa': 2.0e5,
                    'temperature_K': 320.0,
                },
                {
                    'name': 'plenum',
                    'type': 'plenum',
                    'initial_pressure_Pa': 1.0e5,
                    'initial_temperature_K': 300.0,
                    'fixed_volume_m3': 0.002,
                    'wall_heat': {'model': 'none'},
                    'combustion': {'model': 'none'},
                    'evaporation': {'model': 'none'},
                },
            ],
            'connections': [
                {
                    'name': 'throttle',
                    'type': 'orifice',
                    'from_volume': 'ambient',
                    'to_volume': 'plenum',
                    'area_m2': 1.0e-4,
                    'forward_cd': 0.7,
                    'reverse_cd': 0.5,
                }
            ],
        },
        'simulation': {
            'dt_s': 1.0e-5,
            'total_cycles': 1,
            'save_last_cycles': 1,
            'solver': {'kind': 'rk4', 'rtol': 1.0e-6, 'atol': 1.0e-9},
        },
        'postprocessing': {
            'csv_path': 'results/out.csv',
            'csv_separator': ';',
            'sampling': {'mode': 'time', 'step_s': 1.0e-4},
            'final_cycle_uniform_angle_export': {'enabled': False, 'step_deg': 1.0},
            'check_report': {'enabled': False, 'html_enabled': False},
        },
    }


def test_environment_and_orifice_are_built_into_model_bundle(tmp_path: Path) -> None:
    cfg = RootConfig.model_validate(_base_config_dict())
    bundle = build_model_bundle(cfg, tmp_path / 'config.yaml')

    assert int(bundle.vol_matrix[0, VolumeCol.TYPE]) == int(VolumeType.ENVIRONMENT)
    assert int(bundle.conn_matrix[0, ConnCol.TYPE]) == int(ConnectionType.ORIFICE)
    assert int(bundle.environment_is_fixed[0]) == 1
    assert bundle.environment_pressures_pa[0] == 2.0e5
    assert bundle.environment_temperatures_K[0] == 320.0
    assert bundle.y_init[0] == 0.0
    assert bundle.y_init[1] == 0.0


def test_rhs_keeps_environment_state_fixed_and_feeds_plenum(tmp_path: Path) -> None:
    cfg = RootConfig.model_validate(_base_config_dict())
    bundle = build_model_bundle(cfg, tmp_path / 'config.yaml')
    rhs = RHSWrapper(bundle)

    dy = rhs(0.0, bundle.y_init.copy())

    assert dy[0] == 0.0
    assert dy[1] == 0.0
    assert dy[2] > 0.0
    assert dy[3] > 0.0


def test_result_rows_report_fixed_environment_pressure_and_temperature(tmp_path: Path) -> None:
    cfg = RootConfig.model_validate(_base_config_dict())
    bundle = build_model_bundle(cfg, tmp_path / 'config.yaml')

    t = np.array([0.0], dtype=np.float64)
    y = bundle.y_init.reshape(-1, 1)
    cycle_indices = np.array([0], dtype=np.int64)
    rows = ResultRowBuilder.build(bundle, t, y, cycle_indices)

    assert rows[0]['ambient_p_Pa'] == 2.0e5
    assert rows[0]['ambient_T_K'] == 320.0
    assert rows[0]['throttle_A_geom_m2'] == 1.0e-4
    assert rows[0]['throttle_A_eff_forward_m2'] == 7.0e-5
    assert rows[0]['throttle_A_eff_reverse_m2'] == 5.0e-5
