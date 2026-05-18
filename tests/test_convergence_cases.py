from __future__ import annotations

import shutil
from pathlib import Path

import numpy as np
import yaml

from thermo0d.app.runner import run_simulation
from thermo0d.input.config_loader import ConfigLoader

from tests.support_test_cases import case_dir


CONFIG_ROOT = Path('test_cases/configs')


def _copy_case_tree(case_name: str) -> Path:
    case_root = case_dir(case_name)
    work_root = case_root / 'work'
    if work_root.exists():
        shutil.rmtree(work_root)
    shutil.copytree(CONFIG_ROOT, work_root)
    return work_root


def _run_case(case_name: str, config_name: str):
    case_root = _copy_case_tree(case_name)
    cfg_path = case_root / config_name
    return run_simulation(cfg_path, excel=False), cfg_path


def _summary_array(artifacts):
    rows = []
    for s in artifacts.cycle_summaries:
        rows.append([float(s.air_mass_mg), float(s.piston_work_J), float(s.pmax_bar)])
    return np.asarray(rows, dtype=float)


def test_convergence_configs_are_schema_valid() -> None:
    out_dir = case_dir('convergence_schema_valid')
    checked = []
    for path in sorted(CONFIG_ROOT.glob('config_2*.yaml')):
        cfg = ConfigLoader.load(path)
        checked.append(path.name)
        assert cfg.test_description is not None
        assert len(cfg.test_description) > 10
    (out_dir / 'validated_configs.txt').write_text('\n'.join(checked), encoding='utf-8')


def test_last_cycles_converge_for_4t_reference_case() -> None:
    artifacts, _ = _run_case('convergence_last_cycles', 'config_25_4t_settling_conv.yaml')
    arr = _summary_array(artifacts)
    assert arr.shape[0] >= 3
    prev = arr[-2]
    last = arr[-1]
    rel = np.abs((last - prev) / np.maximum(np.abs(last), np.array([1.0, 1.0, 1.0])))
    assert rel[0] < 0.10
    assert rel[1] < 0.20
    assert rel[2] < 0.10


def test_timestep_refinement_converges_between_coarse_and_fine_rk4() -> None:
    fine, _ = _run_case('convergence_rk4_fine', 'config_21_4t_conv_rk4_fine.yaml')
    coarse, _ = _run_case('convergence_rk4_coarse', 'config_20_4t_conv_rk4_coarse.yaml')
    fine_last = _summary_array(fine)[-1]
    coarse_last = _summary_array(coarse)[-1]
    rel = np.abs((fine_last - coarse_last) / np.maximum(np.abs(fine_last), np.array([1.0, 1.0, 1.0])))
    assert rel[0] < 0.15
    assert rel[1] < 0.25
    assert rel[2] < 0.15


def test_solver_agreement_between_rk4_and_scipy_reference_case() -> None:
    rk4, _ = _run_case('convergence_solver_rk4', 'config_20_4t_conv_rk4_coarse.yaml')
    scipy, _ = _run_case('convergence_solver_scipy', 'config_22_4t_conv_scipy.yaml')
    rk4_last = _summary_array(rk4)[-1]
    scipy_last = _summary_array(scipy)[-1]
    rel = np.abs((rk4_last - scipy_last) / np.maximum(np.abs(scipy_last), np.array([1.0, 1.0, 1.0])))
    assert rel[0] < 0.20
    assert rel[1] < 0.30
    assert rel[2] < 0.20


def test_two_cylinder_4t_convergence_case_runs_with_finite_cycle_summaries() -> None:
    artifacts, cfg_path = _run_case('convergence_two_cyl_4t', 'config_23_4t_two_cyl_conv.yaml')
    cfg = yaml.safe_load(cfg_path.read_text(encoding='utf-8'))
    cylinder_count = sum(1 for vol in cfg['preprocessing']['volumes'] if vol['type'] == 'cylinder')
    arr = _summary_array(artifacts)
    assert cylinder_count == 2
    assert arr.shape[0] >= 3
    assert np.all(np.isfinite(arr))
    assert np.all(arr[:, 0] > 0.0)
    assert np.all(arr[:, 2] > 0.0)


def test_two_cylinder_2t_convergence_case_runs_with_finite_cycle_summaries() -> None:
    artifacts, cfg_path = _run_case('convergence_two_cyl_2t', 'config_24_2t_two_cyl_conv.yaml')
    cfg = yaml.safe_load(cfg_path.read_text(encoding='utf-8'))
    cylinder_count = sum(1 for vol in cfg['preprocessing']['volumes'] if vol['type'] == 'cylinder')
    arr = _summary_array(artifacts)
    assert cylinder_count == 2
    assert arr.shape[0] >= 3
    assert np.all(np.isfinite(arr))
    assert np.all(arr[:, 0] > 0.0)
    assert np.all(arr[:, 2] > 0.0)
