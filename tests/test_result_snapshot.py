from __future__ import annotations

import shutil
from pathlib import Path

from thermo0d.app.runner import run_simulation
from tests.test_runner import _prepare_case



def test_run_simulation_copies_config_data_and_plot_layouts_into_result_dir():
    work_dir, cfg = _prepare_case(
        'runner_check_report_html',
        'Projekte/config_1cyl_4t.yaml',
        'config_snapshot.yaml',
        'run_snapshot.csv',
    )
    shutil.copy2(Path('Projekte/plot.yaml'), work_dir / 'plot.yaml')

    text = cfg.read_text(encoding='utf-8').replace(str((work_dir / 'run_snapshot.csv').as_posix()), 'results/run_snapshot.csv')
    text += (
        '\n  excel_enabled: true\n'
        '  final_cycle_uniform_angle_export:\n'
        '    enabled: true\n'
        '    step_deg: 2.0\n'
        '  check_report:\n'
        '    enabled: true\n'
        '    html_enabled: true\n'
        '  plots:\n'
        '    enabled: true\n'
        '    source: export_rows\n'
        '    output_dir: results/plots\n'
        '    layouts:\n'
        '      auto_create_defaults: false\n'
        '      entries:\n'
        '        - enabled: true\n'
        '          path: plot.yaml\n'
        '          prefix: snapshot\n'
    )
    cfg.write_text(text, encoding='utf-8')

    artifacts = run_simulation(cfg, excel=None)
    case_dir = Path(artifacts.csv_path).parents[1]
    results_dir = case_dir / 'results'
    plots_dir = case_dir / 'plots'

    assert Path(artifacts.csv_path).parent == results_dir
    assert (case_dir / cfg.name).exists()
    assert (case_dir / 'data' / 'intake_valve_lift.csv').exists()
    assert (case_dir / 'data' / 'exhaust_alpha_k.csv').exists()
    assert (case_dir / 'plot.yaml').exists()
    assert artifacts.generated_plot_paths
    assert all(Path(p).parent == plots_dir for p in artifacts.generated_plot_paths)
    assert any(Path(p).suffix.lower() == '.png' and Path(p).exists() for p in artifacts.generated_plot_paths)
