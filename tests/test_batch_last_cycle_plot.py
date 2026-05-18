from pathlib import Path
import shutil

from thermo0d.app.paths import PathManager
from thermo0d.app.runner import run_simulation


def test_run_simulation_writes_last_cycle_pressure_plot_to_shared_testcases_dir(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project_root = tmp_path / 'project'
    (project_root / 'test_cases' / 'configs').mkdir(parents=True)
    src = (repo_root / 'test_cases' / 'configs' / 'config_01_4t_base.yaml').read_text(encoding='utf-8')
    patched = src.replace('results/config_01_4t_base.csv', str((tmp_path / 'run.csv').as_posix()))
    cfg = tmp_path / 'config.yaml'
    cfg.write_text(patched, encoding='utf-8')
    data_src = repo_root / 'test_cases' / 'configs' / 'data'
    data_dst = tmp_path / 'data'
    shutil.copytree(data_src, data_dst)
    PathManager.override(project_root=project_root, default_project=project_root / 'Projekte', default_test_space=project_root / 'test_space', default_variants_dir=project_root / 'test_cases' / 'configs')
    artifacts = run_simulation(cfg, excel=False)
    assert artifacts.last_cycle_pressure_plot_path is not None
    plot_path = Path(artifacts.last_cycle_pressure_plot_path)
    assert plot_path.exists()
    assert plot_path.suffix == '.png'
    assert plot_path.parent == project_root / 'test_cases' / 'plots'
    assert plot_path.name == 'config_last_cycle_pressure_mdot.png'
    assert artifacts.plot_layout_path is not None
    assert Path(artifacts.plot_layout_path).exists()
    assert artifacts.generated_plot_paths
    assert Path(artifacts.generated_plot_paths[0]).exists()


def test_run_simulation_exports_energy_balance_signals(tmp_path: Path):
    repo_root = Path(__file__).resolve().parents[1]
    project_root = tmp_path / 'project'
    (project_root / 'test_cases' / 'configs').mkdir(parents=True)
    src = (repo_root / 'test_cases' / 'configs' / 'config_01_4t_base.yaml').read_text(encoding='utf-8')
    patched = src.replace('results/config_01_4t_base.csv', 'results/run.csv')
    cfg = tmp_path / 'config.yaml'
    cfg.write_text(patched, encoding='utf-8')
    data_src = repo_root / 'test_cases' / 'configs' / 'data'
    data_dst = tmp_path / 'data'
    shutil.copytree(data_src, data_dst)
    PathManager.override(project_root=project_root, default_project=project_root / 'Projekte', default_test_space=project_root / 'test_space', default_variants_dir=project_root / 'test_cases' / 'configs')
    artifacts = run_simulation(cfg, excel=False)
    first_row = artifacts.export_rows[-1]
    assert 'cylinder_delta_U_cycle_J' in first_row
    assert 'cylinder_enthalpy_net_cycle_J' in first_row
    assert 'cylinder_energy_balance_residual_J' in first_row
    plot_yaml = Path(artifacts.plot_layout_path)
    text = plot_yaml.read_text(encoding='utf-8')
    assert 'events:' in text
    assert 'Energiebilanz kumuliert' in text
