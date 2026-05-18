from pathlib import Path

import yaml

from thermo0d.app.paths import PathManager
from thermo0d.app.runner import run_simulation


def _patch_config(base_config: Path, target: Path, *, outdir: str | None = None) -> Path:
    data = yaml.safe_load(base_config.read_text(encoding='utf-8'))
    source_data_dir = (Path('Projekte/data').resolve() if Path('Projekte/data').exists() else base_config.parent / 'data')
    if source_data_dir.is_dir():
        target_data_dir = target.parent / 'data'
        target_data_dir.mkdir(parents=True, exist_ok=True)
        for src in source_data_dir.iterdir():
            if src.is_file():
                (target_data_dir / src.name).write_bytes(src.read_bytes())
    post = data.setdefault('postprocessing', {})
    post['csv_path'] = 'results/out.csv'
    post['excel_enabled'] = True
    post['excel_path'] = 'results/out.xlsx'
    post.setdefault('check_report', {})['enabled'] = True
    post['check_report']['html_enabled'] = True
    post.setdefault('final_cycle_uniform_angle_export', {})['enabled'] = True
    post['final_cycle_uniform_angle_export']['step_deg'] = 5.0
    post.setdefault('plots', {})['enabled'] = False
    if outdir is None:
        post.pop('outdir', None)
    else:
        post['outdir'] = outdir
    target.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    return target


def test_simulation_outputs_use_default_truncated_output_dir(tmp_path: Path):
    base = Path('test_cases/configs/config_01_4t_base.yaml').resolve()
    config_path = _patch_config(base, tmp_path / 'A156A1-2V-REX-V09d_WH02-Vibe_PP_RK45.yaml')
    artifacts = run_simulation(config_path)
    out_dir = tmp_path / 'results' / PathManager.default_output_dir_name(config_path)
    assert Path(artifacts.csv_path) == (out_dir / 'results' / 'out.csv').resolve()
    assert Path(artifacts.excel_path) == (out_dir / 'results' / 'out.xlsx').resolve()
    assert Path(artifacts.last_cycle_uniform_csv_path) == (out_dir / 'results' / 'out_last_cycle_uniform.csv').resolve()
    assert Path(artifacts.check_report_csv_path) == (out_dir / 'results' / 'out_check_report.csv').resolve()
    assert Path(artifacts.check_report_html_path) == (out_dir / 'results' / 'out_check_report.html').resolve()
    assert (out_dir / config_path.name).exists()


def test_simulation_outputs_use_configured_postprocessing_outdir(tmp_path: Path):
    base = Path('test_cases/configs/config_01_4t_base.yaml').resolve()
    config_path = _patch_config(base, tmp_path / 'demo_config.yaml', outdir='my_named_result_folder')
    artifacts = run_simulation(config_path)
    out_dir = tmp_path / 'results' / PathManager.make_collision_safe_output_dir_name('my_named_result_folder')
    assert Path(artifacts.csv_path) == (out_dir / 'results' / 'out.csv').resolve()
    assert Path(artifacts.excel_path) == (out_dir / 'results' / 'out.xlsx').resolve()
    assert (out_dir / config_path.name).exists()
