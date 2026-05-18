from __future__ import annotations

from pathlib import Path

import numpy as np

from thermo0d.compute.analysis import CycleIndexCalculator
from thermo0d.compute.executor import SimulationExecutor
from thermo0d.config.constants import ConnectionType, VolumeCol, VolumeType
from thermo0d.config.models import RootConfig
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.output.rows import ResultRowBuilder
from thermo0d.model.free_piston.rhs import compute_free_piston_rhs


def _coldflow_config_dict() -> dict:
    return {
        'test_description': 'free-piston-coldflow',
        'modeling': {'architecture': 'free_piston'},
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
                'pv_work': True,
            },
            'engine': {
                'cycle_type': '2t',
                'speed_rpm': 25.0,
            },
            'volumes': [
                {
                    'name': 'cylinder',
                    'type': 'cylinder',
                    'initial_pressure_Pa': 120000.0,
                    'initial_temperature_K': 320.0,
                    'kinematics': {
                        'type': 'crank_slider',
                        'bore_m': 0.0745,
                        'stroke_m': 0.0745,
                        'conrod_m': 0.12,
                        'compression_ratio': 10.0,
                        'phase_deg': 0.0,
                    },
                    'wall_heat': {'model': 'none'},
                    'combustion': {'model': 'none'},
                    'evaporation': {'model': 'none'},
                },
                {
                    'name': 'scavenge_plenum',
                    'type': 'plenum',
                    'initial_pressure_Pa': 160000.0,
                    'initial_temperature_K': 300.0,
                    'fixed_volume_m3': 0.002,
                    'wall_heat': {'model': 'none'},
                    'combustion': {'model': 'none'},
                    'evaporation': {'model': 'none'},
                },
                {
                    'name': 'exhaust_plenum',
                    'type': 'plenum',
                    'initial_pressure_Pa': 110000.0,
                    'initial_temperature_K': 330.0,
                    'fixed_volume_m3': 0.0025,
                    'wall_heat': {'model': 'none'},
                    'combustion': {'model': 'none'},
                    'evaporation': {'model': 'none'},
                },
                {
                    'name': 'ambient_in',
                    'type': 'environment',
                    'pressure_Pa': 180000.0,
                    'temperature_K': 300.0,
                },
                {
                    'name': 'ambient_out',
                    'type': 'environment',
                    'pressure_Pa': 101325.0,
                    'temperature_K': 300.0,
                },
            ],
            'connections': [
                {
                    'name': 'scavenge_feed',
                    'type': 'orifice',
                    'from_volume': 'ambient_in',
                    'to_volume': 'scavenge_plenum',
                    'area_m2': 8.0e-5,
                    'forward_cd': 0.75,
                    'reverse_cd': 0.60,
                },
                {
                    'name': 'transfer_slot',
                    'type': 'slot',
                    'from_volume': 'scavenge_plenum',
                    'to_volume': 'cylinder',
                    'source_of_data': 'rectangle',
                    'opening_mode': 'by_distance',
                    'distance_from_tdc_m': 0.010,
                    'opening_angle_deg': None,
                    'piston_height_if_crankcase_m': 0.0,
                    'entrance_angle_deg': 0.0,
                    'width_m': 0.020,
                    'height_m': 0.012,
                    'open_fillet_radius_m': 0.0,
                    'full_fillet_radius_m': 0.0,
                    'number_of_identical_holes': 2,
                    'discharge_coefficients': {
                        'mode': 'constant',
                        'forward_cd': 0.82,
                        'reverse_cd': 0.68,
                    },
                },
                {
                    'name': 'exhaust_slot',
                    'type': 'slot',
                    'from_volume': 'cylinder',
                    'to_volume': 'exhaust_plenum',
                    'source_of_data': 'rectangle',
                    'opening_mode': 'by_distance',
                    'distance_from_tdc_m': 0.006,
                    'opening_angle_deg': None,
                    'piston_height_if_crankcase_m': 0.0,
                    'entrance_angle_deg': 0.0,
                    'width_m': 0.024,
                    'height_m': 0.014,
                    'open_fillet_radius_m': 0.0,
                    'full_fillet_radius_m': 0.0,
                    'number_of_identical_holes': 2,
                    'discharge_coefficients': {
                        'mode': 'constant',
                        'forward_cd': 0.78,
                        'reverse_cd': 0.70,
                    },
                },
                {
                    'name': 'exhaust_bleed',
                    'type': 'orifice',
                    'from_volume': 'exhaust_plenum',
                    'to_volume': 'ambient_out',
                    'area_m2': 1.2e-4,
                    'forward_cd': 0.72,
                    'reverse_cd': 0.55,
                },
            ],
        },
        'simulation': {
            'dt_s': 1.0e-5,
            'total_cycles': 1,
            'save_last_cycles': 1,
            'simulationtime': 0.005,
            'solver': {'kind': 'rk4', 'rtol': 1.0e-6, 'atol': 1.0e-9},
        },
        'postprocessing': {
            'csv_path': 'results/free_piston_coldflow.csv',
            'csv_separator': ';',
            'sampling': {'mode': 'time', 'step_s': 1.0e-4},
            'final_cycle_uniform_angle_export': {'enabled': False, 'step_deg': 1.0},
            'check_report': {'enabled': False, 'html_enabled': False},
            'console': {
                'run_summary': {'enabled': False},
                'cycle_summary': {'enabled': False},
                'check_report': {'enabled': False},
                'geometry': {'enabled': False},
            },
            'plots': {'enabled': False, 'source': 'export_rows', 'layouts': {'auto_create_defaults': False}},
        },
        'free_piston': {
            'initial_conditions': {
                'x0_m': 0.020,
                'v0_m_per_s': -0.2,
                'cylinder': {'pressure_Pa': 120000.0, 'temperature_K': 320.0},
                'bounce': {'pressure_Pa': 140000.0, 'temperature_K': 300.0},
            },
            'mechanics': {
                'moving_mass_kg': 2.0,
                'piston_area_m2': 0.00436,
                'clearance_volume_m3': 2.5e-5,
                'x_min_m': -0.04,
                'x_max_m': 0.04,
            },
            'friction': {
                'model': 'coulomb_viscous',
                'fc_N': 20.0,
                'cv_Ns_per_m': 10.0,
            },
            'load': {
                'model': 'viscous',
                'damping_Ns_per_m': 120.0,
            },
            'bounce': {
                'model': 'gas_spring',
                'chamber_volume0_m3': 3.0e-4,
                'p0_Pa': 150000.0,
                'polytropic_exponent': 1.30,
            },
        },
    }


def test_free_piston_coldflow_bundle_builds_shared_topology(tmp_path: Path) -> None:
    cfg = RootConfig.model_validate(_coldflow_config_dict())
    bundle = build_model_bundle(cfg, tmp_path / 'free_piston_coldflow.yaml')

    assert bundle.architecture == 'free_piston'
    assert bundle.volume_names == ['cylinder', 'scavenge_plenum', 'exhaust_plenum', 'ambient_in', 'ambient_out']
    assert bundle.connection_names == ['scavenge_feed', 'transfer_slot', 'exhaust_slot', 'exhaust_bleed']
    assert int(bundle.vol_matrix[0, VolumeCol.TYPE]) == int(VolumeType.CYLINDER)
    assert [int(row[0]) for row in bundle.conn_matrix] == [
        int(ConnectionType.ORIFICE),
        int(ConnectionType.SLOT),
        int(ConnectionType.SLOT),
        int(ConnectionType.ORIFICE),
    ]
    assert bundle.kin_matrix.shape[0] == 0


def test_free_piston_coldflow_rhs_has_massflow_and_runs(tmp_path: Path) -> None:
    cfg = RootConfig.model_validate(_coldflow_config_dict())
    bundle = build_model_bundle(cfg, tmp_path / 'free_piston_coldflow.yaml')

    dy = compute_free_piston_rhs(0.0, bundle.y_init.copy(), bundle)
    cyl_m_idx = bundle.state_layout.mass_index(bundle.cylinder_indices[0])
    scav_m_idx = bundle.state_layout.mass_index(1)
    exh_m_idx = bundle.state_layout.mass_index(2)

    assert abs(float(dy[cyl_m_idx])) > 0.0
    assert abs(float(dy[scav_m_idx])) > 0.0
    assert abs(float(dy[exh_m_idx])) > 0.0

    result = SimulationExecutor(bundle).run()
    assert result.t.size > 5
    assert np.all(np.isfinite(result.y))

    cycle_indices = CycleIndexCalculator.compute(result.t, bundle.cycle_period_s, bundle.simulation.total_cycles)
    rows = ResultRowBuilder.build(bundle, result.t[:1], result.y[:, :1], cycle_indices[:1])
    assert 'transfer_slot_A_eff_forward_m2' in rows[0]
    assert 'exhaust_slot_A_eff_forward_m2' in rows[0]
    assert 'scavenge_feed_A_eff_forward_m2' in rows[0]
