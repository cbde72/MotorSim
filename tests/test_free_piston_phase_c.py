from __future__ import annotations

from pathlib import Path

import yaml

from thermo0d.app.runner import run_simulation
from thermo0d.gui.signal_catalog import build_signal_catalog_for_project
from thermo0d.output.check_report import LastCycleCheckReportBuilder
from thermo0d.output.geometry_report import build_geometry_entries
from thermo0d.input.config_loader import ConfigLoader
from thermo0d.input.model_builder import build_model_bundle


def _phase_c_config(tmp_path: Path) -> Path:
    src = Path('Projekte/variants/free_piston_phase_a3.yaml').resolve()
    data = yaml.safe_load(src.read_text(encoding='utf-8'))
    post = data.setdefault('postprocessing', {})
    post['csv_enabled'] = True
    post['csv_path'] = 'results/out.csv'
    post['excel_enabled'] = False
    post.setdefault('check_report', {})['enabled'] = True
    post['check_report']['html_enabled'] = True
    post.setdefault('final_cycle_uniform_angle_export', {})['enabled'] = False
    post.setdefault('plots', {})['enabled'] = False
    post.setdefault('console', {}).setdefault('check_report', {})['enabled'] = True
    post['console'].setdefault('geometry', {})['enabled'] = True
    out = tmp_path / 'free_piston_phase_c.yaml'
    out.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')
    return out


def test_free_piston_geometry_entries_include_mechanics() -> None:
    cfg_path = Path('Projekte/variants/free_piston_phase_a3.yaml').resolve()
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    entries = build_geometry_entries(bundle)
    keys = {entry.key for entry in entries}
    assert 'cylinder_moving_mass_kg' in keys
    assert 'cylinder_piston_area_mm2' in keys
    assert 'cylinder_stroke_window_mm' in keys


def test_free_piston_check_report_adds_oscillation_metrics() -> None:
    rows = [
        {'t_s': 0.00, 'cycle_index': 0, 'free_piston_x_m': 0.000, 'free_piston_v_m_per_s': 1.0, 'cylinder_p_Pa': 101325.0, 'cylinder_T_K': 300.0, 'cylinder_m_kg': 0.001, 'cylinder_U_J': 200.0},
        {'t_s': 0.01, 'cycle_index': 0, 'free_piston_x_m': 0.010, 'free_piston_v_m_per_s': 0.0, 'cylinder_p_Pa': 120000.0, 'cylinder_T_K': 320.0, 'cylinder_m_kg': 0.001, 'cylinder_U_J': 210.0},
        {'t_s': 0.02, 'cycle_index': 0, 'free_piston_x_m': 0.000, 'free_piston_v_m_per_s': -1.0, 'cylinder_p_Pa': 110000.0, 'cylinder_T_K': 310.0, 'cylinder_m_kg': 0.001, 'cylinder_U_J': 205.0},
        {'t_s': 0.03, 'cycle_index': 0, 'free_piston_x_m': -0.010, 'free_piston_v_m_per_s': 0.0, 'cylinder_p_Pa': 90000.0, 'cylinder_T_K': 295.0, 'cylinder_m_kg': 0.001, 'cylinder_U_J': 198.0},
        {'t_s': 0.04, 'cycle_index': 0, 'free_piston_x_m': 0.000, 'free_piston_v_m_per_s': 1.0, 'cylinder_p_Pa': 101325.0, 'cylinder_T_K': 300.0, 'cylinder_m_kg': 0.001, 'cylinder_U_J': 200.0},
    ]
    metrics = LastCycleCheckReportBuilder.build_metrics(rows, cycle_deg=360.0, bundle=None)
    names = {metric.name for metric in metrics}
    assert 'free_piston_turning_points_count' not in names

    cfg_path = Path('Projekte/variants/free_piston_phase_a3.yaml').resolve()
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    metrics = LastCycleCheckReportBuilder.build_metrics(rows, cycle_deg=360.0, bundle=bundle)
    names = {metric.name for metric in metrics}
    assert 'free_piston_turning_points_count' in names
    assert 'free_piston_mean_frequency_Hz' in names
    assert 'free_piston_last_halfstroke_m' in names


def test_free_piston_runner_writes_check_report_and_console_output(tmp_path: Path, capsys) -> None:
    cfg_path = _phase_c_config(tmp_path)
    artifacts = run_simulation(cfg_path, excel=False)
    out = capsys.readouterr().out
    assert artifacts.csv_path is not None and Path(artifacts.csv_path).exists()
    assert artifacts.check_report_csv_path is not None and Path(artifacts.check_report_csv_path).exists()
    assert artifacts.check_report_html_path is not None and Path(artifacts.check_report_html_path).exists()
    assert '[check-report] last-cycle summary' in out
    assert '[geometry:free_piston]' in out


def test_signal_catalog_temp_project_includes_free_piston_entries(tmp_path: Path) -> None:
    project_dir = tmp_path / 'Projekte'
    project_dir.mkdir()
    cfg_path = project_dir / 'free_piston.yaml'
    cfg_path.write_text(Path('Projekte/variants/free_piston_phase_a3.yaml').read_text(encoding='utf-8'), encoding='utf-8')
    catalog = build_signal_catalog_for_project(project_dir)
    full = set(catalog['full'])
    assert 'cylinder_p_Pa' in full
    assert 'free_piston_x_m' in full
    assert 'free_piston_F_net_N' in full
    assert 'bounce_pressure_Pa' in full
