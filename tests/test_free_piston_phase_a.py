from pathlib import Path

import pytest
import yaml

from thermo0d.compute.executor import SimulationExecutor
from thermo0d.config.models import RootConfig
from thermo0d.input.config_loader import ConfigLoader
from thermo0d.input.model_builder import build_model_bundle


def test_free_piston_phase_a_bundle_contains_architecture_and_extra_states() -> None:
    cfg_path = Path('Projekte/variants/free_piston_phase_a.yaml').resolve()
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)

    assert cfg.modeling.architecture == 'free_piston'
    assert bundle.architecture == 'free_piston'
    assert bundle.state_layout is not None
    assert bundle.state_layout.has_free_piston_states is True
    assert bundle.free_piston is not None
    x_idx, v_idx = bundle.state_layout.free_piston_indices()
    assert bundle.y_init.shape[0] == 2 * len(bundle.volume_names) + 2
    assert float(bundle.y_init[x_idx]) == pytest.approx(cfg.free_piston.initial_conditions.x0_m)
    assert float(bundle.y_init[v_idx]) == pytest.approx(cfg.free_piston.initial_conditions.v0_m_per_s)


def test_free_piston_phase_a_uses_free_piston_cylinder_initial_state() -> None:
    cfg_path = Path('Projekte/variants/free_piston_phase_a.yaml').resolve()
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)

    assert bundle.free_piston is not None
    assert bundle.y_init[0] == pytest.approx(bundle.free_piston.initial_cylinder_mass_kg)
    assert bundle.y_init[1] == pytest.approx(bundle.free_piston.initial_cylinder_internal_energy_J)
    assert bundle.free_piston.initial_cylinder_volume_m3 > 0.0


def test_free_piston_phase_a_execution_runs_minimal_a2_path() -> None:
    cfg_path = Path('Projekte/variants/free_piston_phase_a.yaml').resolve()
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    result = SimulationExecutor(bundle).run()
    assert result.t.size > 2
    assert result.y.shape[1] == result.t.size


def test_free_piston_uses_preprocessing_cylinder_initial_conditions() -> None:
    cfg_path = Path('Projekte/variants/free_piston_phase_a.yaml').resolve()
    raw = yaml.safe_load(cfg_path.read_text(encoding='utf-8'))
    raw.pop('versioning', None)
    raw['preprocessing']['volumes'] = [{
        'name': 'cylinder',
        'type': 'cylinder',
        'initial_pressure_Pa': 200000.0,
        'initial_temperature_K': 300.0,
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
    }]
    raw['free_piston']['initial_conditions'].pop('cylinder', None)

    cfg = RootConfig.model_validate(raw)
    bundle = build_model_bundle(cfg, cfg_path)

    assert bundle.free_piston is not None
    assert bundle.free_piston.cylinder_pressure_Pa == pytest.approx(200000.0)
    assert bundle.free_piston.cylinder_temperature_K == pytest.approx(300.0)


def test_free_piston_phase_a_builds_without_classic_cylinder_placeholder() -> None:
    cfg_path = Path('Projekte/variants/free_piston_phase_a.yaml').resolve()
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    assert bundle.architecture == 'free_piston'
    assert bundle.cylinder_indices == [0]
    assert bundle.volume_names == ['cylinder']
