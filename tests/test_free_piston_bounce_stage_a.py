from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from thermo0d.compute.analysis import CycleIndexCalculator
from thermo0d.compute.executor import SimulationExecutor
from thermo0d.config.constants import VolumeCol, VolumeType
from thermo0d.config.models import RootConfig
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.model.free_piston.rhs import compute_free_piston_rhs
from thermo0d.output.rows import ResultRowBuilder


def _stage_a_config_dict() -> dict:
    return {
        'test_description': 'free-piston-bounce-stage-a',
        'modeling': {'architecture': 'free_piston'},
        'preprocessing': {
            'gas_properties': {'cp_J_per_kgK': 1005.0, 'cv_J_per_kgK': 718.0, 'R_J_per_kgK': 287.0},
            'features': {'mass_flow': True, 'wall_heat': False, 'combustion': False, 'evaporation': False, 'pv_work': True},
            'engine': {'cycle_type': '2t', 'speed_rpm': 25.0},
            'volumes': [
                {
                    'name': 'cylinder',
                    'type': 'cylinder',
                    'initial_pressure_Pa': 120000.0,
                    'initial_temperature_K': 320.0,
                    'kinematics': {
                        'type': 'crank_slider',
                        'bore_m': 0.0745,
                        'stroke_m': 0.08,
                        'conrod_m': 0.12,
                        'compression_ratio': 10.0,
                        'phase_deg': 0.0,
                    },
                    'wall_heat': {'model': 'none'},
                    'combustion': {'model': 'none'},
                    'evaporation': {'model': 'none'},
                },
                {
                    'name': 'bounce',
                    'type': 'bounce_chamber',
                    'model': 'gas_exchange',
                    'initial_pressure_Pa': 110000.0,
                    'initial_temperature_K': 300.0,
                    'chamber_diameter_m': 0.055,
                    'chamber_length_m': 0.08,
                    'compression_ratio': 2.5,
                    'polytropic_exponent': 1.30,
                },
                {'name': 'ambient_in', 'type': 'environment', 'pressure_Pa': 101325.0, 'temperature_K': 300.0},
                {'name': 'ambient_out', 'type': 'environment', 'pressure_Pa': 101325.0, 'temperature_K': 300.0},
            ],
            'connections': [
                {
                    'name': 'bounce_in',
                    'type': 'orifice',
                    'from_volume': 'ambient_in',
                    'to_volume': 'bounce',
                    'area_m2': 4.0e-5,
                    'forward_cd': 0.72,
                    'reverse_cd': 0.40,
                },
                {
                    'name': 'bounce_out',
                    'type': 'orifice',
                    'from_volume': 'bounce',
                    'to_volume': 'ambient_out',
                    'area_m2': 4.0e-5,
                    'forward_cd': 0.72,
                    'reverse_cd': 0.40,
                },
            ],
        },
        'simulation': {
            'dt_s': 1.0e-5,
            'total_cycles': 1,
            'save_last_cycles': 1,
            'simulationtime': 0.001,
            'solver': {'kind': 'rk4', 'rtol': 1.0e-6, 'atol': 1.0e-9},
        },
        'postprocessing': {
            'csv_enabled': False,
            'excel_enabled': False,
            'sampling': {'mode': 'time', 'step_s': 1.0e-4},
            'final_cycle_uniform_angle_export': {'enabled': False, 'step_deg': 1.0},
            'check_report': {'enabled': False, 'html_enabled': False},
            'plots': {'enabled': False, 'source': 'export_rows', 'layouts': {'auto_create_defaults': False}},
            'console': {
                'run_summary': {'enabled': False},
                'cycle_summary': {'enabled': False},
                'check_report': {'enabled': False},
                'geometry': {'enabled': False},
            },
        },
        'free_piston': {
            'initial_conditions': {
                'x0_m': 0.01,
                'v0_m_per_s': -0.2,
                'cylinder': {'pressure_Pa': 120000.0, 'temperature_K': 320.0},
            },
            'mechanics': {
                'moving_mass_kg': 2.0,
                'piston_area_m2': 0.00436,
                'clearance_volume_m3': 2.5e-5,
                'x_min_m': 0.0,
                'x_max_m': 0.08,
            },
            'friction': {'model': 'coulomb_viscous', 'fc_N': 20.0, 'cv_Ns_per_m': 10.0},
            'load': {'model': 'viscous', 'damping_Ns_per_m': 120.0},
        },
    }


def test_free_piston_stage_a_bounce_builds_as_stateful_volume(tmp_path: Path) -> None:
    cfg = RootConfig.model_validate(_stage_a_config_dict())
    bundle = build_model_bundle(cfg, tmp_path / 'free_piston_bounce_stage_a.yaml')

    assert bundle.architecture == 'free_piston'
    assert bundle.volume_names == ['cylinder', 'bounce', 'ambient_in', 'ambient_out']
    assert int(bundle.vol_matrix[1, VolumeCol.TYPE]) == int(VolumeType.BOUNCE_CHAMBER)
    assert float(bundle.y_init[bundle.state_layout.mass_index(1)]) > 0.0
    assert float(bundle.y_init[bundle.state_layout.energy_index(1)]) > 0.0


def test_free_piston_stage_a_bounce_rhs_and_rows_are_finite(tmp_path: Path) -> None:
    cfg = RootConfig.model_validate(_stage_a_config_dict())
    bundle = build_model_bundle(cfg, tmp_path / 'free_piston_bounce_stage_a.yaml')

    dy = compute_free_piston_rhs(0.0, bundle.y_init.copy(), bundle)
    assert np.all(np.isfinite(dy))
    assert abs(float(dy[bundle.state_layout.mass_index(1)])) > 0.0

    result = SimulationExecutor(bundle).run()
    assert result.t.size > 10
    assert np.all(np.isfinite(result.y))

    cycle_indices = CycleIndexCalculator.compute(result.t, bundle.cycle_period_s, bundle.simulation.total_cycles)
    rows = ResultRowBuilder.build(bundle, result.t[:3], result.y[:, :3], cycle_indices[:3])
    assert 'bounce_p_Pa' in rows[0]
    assert 'bounce_V_m3' in rows[0]
    assert 'bounce_pressure_Pa' in rows[0]
    assert rows[0]['bounce_p_Pa'] == pytest.approx(rows[0]['bounce_pressure_Pa'])


def test_free_piston_stage_a_rejects_slot_connections_to_bounce() -> None:
    cfg = _stage_a_config_dict()
    cfg['preprocessing']['connections'][0] = {
        'name': 'bounce_in_slot',
        'type': 'slot',
        'from_volume': 'ambient_in',
        'to_volume': 'bounce',
        'source_of_data': 'rectangle',
        'opening_mode': 'by_distance',
        'distance_from_tdc_m': 0.005,
        'opening_angle_deg': None,
        'piston_height_if_crankcase_m': 0.0,
        'entrance_angle_deg': 0.0,
        'width_m': 0.01,
        'height_m': 0.01,
        'open_fillet_radius_m': 0.0,
        'full_fillet_radius_m': 0.0,
        'number_of_identical_holes': 1,
        'discharge_coefficients': {'mode': 'constant', 'forward_cd': 0.7, 'reverse_cd': 0.7},
    }

    with pytest.raises(ValueError, match='Stage A gas_exchange bounce currently supports only orifice'):
        RootConfig.model_validate(cfg)
