import numpy as np
import shutil
from pathlib import Path

from thermo0d.app.runner import run_simulation

from tests.support_test_cases import case_dir


def _prepare_case(case_name: str, config_src: str, config_out_name: str, out_name: str, replacements: list[tuple[str, str]] | None = None):
    root_dir = case_dir(case_name)
    work_dir = root_dir / 'work'
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    src = Path(config_src).read_text(encoding='utf-8')
    patched = src.replace(Path(config_src).stem.replace('config_', 'results/one_').replace('1cyl_', 'cyl_') if False else '___', '___')
    # explicit output replacement
    if '1cyl_2t' in config_src:
        patched = src.replace('results/one_cyl_2t.csv', str((work_dir / out_name).as_posix()))
    else:
        patched = src.replace('results/one_cyl_4t.csv', str((work_dir / out_name).as_posix()))
    for old, new in (replacements or []):
        patched = patched.replace(old, new)
    cfg = work_dir / config_out_name
    cfg.write_text(patched, encoding='utf-8')
    shutil.copytree(Path('Projekte/data'), work_dir / 'data')
    return work_dir, cfg


def test_run_simulation_creates_csv_and_excel_for_angle_based_sampling():
    _, cfg = _prepare_case('runner_angle_excel', 'Projekte/config_1cyl_2t.yaml', 'config.yaml', 'run.csv')
    artifacts = run_simulation(cfg, excel=True)
    assert Path(artifacts.csv_path).exists()
    assert Path(artifacts.excel_path).exists()


def test_run_simulation_creates_csv_for_time_based_sampling():
    _, cfg = _prepare_case('runner_time_csv', 'Projekte/config_1cyl_4t.yaml', 'config_time.yaml', 'run_time.csv')
    artifacts = run_simulation(cfg, excel=False)
    assert Path(artifacts.csv_path).exists()


def test_cycle_console_output_contains_pmax(capsys):
    _, cfg = _prepare_case('runner_console', 'Projekte/config_1cyl_2t.yaml', 'config_console.yaml', 'run_console.csv')
    run_simulation(cfg, excel=False)
    out = capsys.readouterr().out
    assert 'pmax_bar=' in out


def test_csv_contains_opening_metrics_for_valve_and_slot():
    _, cfg = _prepare_case('runner_metrics_2t', 'Projekte/config_1cyl_2t.yaml', 'config_metrics.yaml', 'run_metrics.csv')
    artifacts = run_simulation(cfg, excel=False)
    first_row = artifacts.export_rows[0]
    assert 'transfer_slot_slot_height_m' in first_row
    assert 'transfer_slot_A_eff_forward_m2' in first_row
    assert 'transfer_slot_A_eff_reverse_m2' in first_row
    assert 'transfer_slot_mdot_kg_per_s' in first_row

    _, cfg4 = _prepare_case('runner_metrics_4t', 'Projekte/config_1cyl_4t.yaml', 'config_metrics_4t.yaml', 'run_metrics_4t.csv')
    artifacts4 = run_simulation(cfg4, excel=False)
    first_row4 = artifacts4.export_rows[0]
    assert 'intake_valve_valve_lift_m' in first_row4
    assert 'intake_valve_A_eff_forward_m2' in first_row4
    assert 'exhaust_valve_A_eff_reverse_m2' in first_row4
    assert 'intake_valve_mdot_kg_per_s' in first_row4
    assert 'exhaust_valve_mdot_kg_per_s' in first_row4



def test_time_based_export_uses_exact_configured_output_step():
    _, cfg = _prepare_case(
        'runner_exact_time',
        'Projekte/config_1cyl_4t.yaml',
        'config_exact_time.yaml',
        'run_exact_time.csv',
        [('mode: crank_angle', 'mode: time'), ('step_deg: 1.0', 'step_s: 0.00013')],
    )
    artifacts = run_simulation(cfg, excel=False)
    times = [float(row['t_s']) for row in artifacts.export_rows]
    diffs = np.diff(np.array(times, dtype=float))
    assert diffs.size > 10
    assert np.allclose(diffs, 0.00013, atol=1.0e-12, rtol=0.0)


def test_angle_based_export_uses_exact_configured_output_step():
    _, cfg = _prepare_case('runner_exact_angle', 'Projekte/config_1cyl_2t.yaml', 'config_exact_angle.yaml', 'run_exact_angle.csv', [('step_deg: 5.0', 'step_deg: 17.0')])
    artifacts = run_simulation(cfg, excel=False)
    times = np.array([float(row['t_s']) for row in artifacts.export_rows], dtype=float)
    diffs = np.diff(times)
    expected_dt = 17.0 / (360.0 / (60.0 / 3000.0))
    assert diffs.size > 10
    assert np.allclose(diffs, expected_dt, atol=1.0e-12, rtol=0.0)
