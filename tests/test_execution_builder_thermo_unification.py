from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from thermo0d.compute.executor import SimulationExecutor, build_time_grid_for_bundle
from thermo0d.input.builder_common import (
    build_feature_flags,
    build_gas_props,
    build_postprocessing_options,
    build_simulation_options,
)
from thermo0d.input.config_loader import ConfigLoader
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.model.free_piston.simulator import build_time_grid, simulate_free_piston
from thermo0d.physics.thermo import mass_from_pTV, pressure_from_state, safe_pressure_from_ideal_gas, safe_temperature_from_state, specific_internal_energy_from_temperature, temperature_from_state


def test_simulate_free_piston_matches_common_executor() -> None:
    cfg_path = Path('Projekte/variants/free_piston_phase_a2.yaml')
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    direct = simulate_free_piston(bundle)
    unified = SimulationExecutor(bundle).run()
    assert np.allclose(direct.t, unified.t)
    assert np.allclose(direct.y, unified.y)
    assert direct.solver_kind == unified.solver_kind


def test_bundle_time_grid_matches_free_piston_compatibility_wrapper() -> None:
    cfg_path = Path('Projekte/variants/free_piston_phase_a2.yaml')
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    assert np.allclose(build_time_grid_for_bundle(bundle), build_time_grid(bundle.simulation.dt_s, bundle.simulation.simulationtime_s))


def test_shared_builder_helpers_match_built_bundle_for_free_piston() -> None:
    cfg_path = Path('Projekte/variants/free_piston_phase_a2.yaml')
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    assert np.allclose(bundle.gas_props, build_gas_props(cfg))
    assert np.array_equal(bundle.feature_flags, build_feature_flags(cfg))
    helper_sim = build_simulation_options(cfg, bundle.cycle_period_s)
    assert bundle.simulation.total_cycles == helper_sim.total_cycles
    assert bundle.simulation.save_last_cycles == helper_sim.save_last_cycles
    helper_post = build_postprocessing_options(cfg)
    assert bundle.postprocessing.sampling_mode == helper_post.sampling_mode
    assert bundle.postprocessing.sampling_step == helper_post.sampling_step


def test_postprocessing_auto_update_flag_is_carried_into_runtime_options() -> None:
    cfg = ConfigLoader.load(Path('Projekte/variants/free_piston_GenSet_V09k.yaml'))
    assert cfg.postprocessing.auto_update_initial_conditions is False

    options = build_postprocessing_options(cfg)

    assert options.auto_update_initial_conditions is False


def test_shared_builder_helpers_match_built_bundle_for_classic(tmp_path) -> None:
    src = Path('Projekte/variants/config_1cyl_2t.yaml').read_text(encoding='utf-8')
    patched = src.replace('csv_path: results/one_cyl_2t.csv', f"csv_path: {(tmp_path / 'classic.csv').as_posix()}")
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    (data_dir / 'slot_cd_table.csv').write_text('0;0.8;0.8\n1;0.8;0.8\n', encoding='utf-8')
    cfg_path = tmp_path / 'classic.yaml'
    cfg_path.write_text(patched, encoding='utf-8')
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    assert np.allclose(bundle.gas_props, build_gas_props(cfg))
    assert np.array_equal(bundle.feature_flags, build_feature_flags(cfg))
    assert bundle.simulation.total_cycles == build_simulation_options(cfg, bundle.cycle_period_s).total_cycles
    assert bundle.postprocessing.csv_path == build_postprocessing_options(cfg).csv_path


def test_shared_thermo_helpers_cover_safe_and_strict_paths() -> None:
    volume = 1.0e-4
    mass = mass_from_pTV(pressure_Pa=2.0e5, temperature_K=600.0, volume_m3=volume, gas_constant_J_per_kgK=287.0)
    u_spec = specific_internal_energy_from_temperature(600.0, 718.0)
    energy = mass * u_spec
    assert temperature_from_state(mass, energy, 718.0) == pytest.approx(600.0)
    assert pressure_from_state(mass, energy, volume, 287.0, 718.0) == pytest.approx(2.0e5)
    assert safe_temperature_from_state(0.0, 0.0, 718.0) == pytest.approx(300.0)
    assert safe_pressure_from_ideal_gas(0.0, 300.0, 287.0, 0.0) == pytest.approx(1.0e3)
