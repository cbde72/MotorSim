from __future__ import annotations

from pathlib import Path

from thermo0d.app.runner import run_simulation
from thermo0d.config_versioning import normalize_config_data
from tests.test_runner import _prepare_case


def test_normalize_config_adds_check_report_defaults():
    cfg = normalize_config_data({
        'preprocessing': {'volumes': [], 'connections': []},
        'simulation': {'solver': {}},
        'postprocessing': {'sampling': {}},
    })
    assert cfg['postprocessing']['check_report']['enabled'] is True
    assert cfg['postprocessing']['check_report']['html_enabled'] is False


def test_run_simulation_creates_last_cycle_check_report_csv():
    _, cfg = _prepare_case('runner_check_report_csv', 'Projekte/config_1cyl_2t.yaml', 'config_check.yaml', 'run_check.csv')
    artifacts = run_simulation(cfg, excel=False)
    assert artifacts.check_report_csv_path is not None
    report_path = Path(artifacts.check_report_csv_path)
    assert report_path.exists()
    text = report_path.read_text(encoding='utf-8')
    assert 'metric' in text and 'status' in text and 'details' in text
    assert 'mass_balance_residual_kg' in text
    assert 'energy_balance_residual_J' in text


def test_run_simulation_optionally_creates_last_cycle_check_report_html():
    _, cfg = _prepare_case('runner_check_report_html', 'Projekte/config_1cyl_4t.yaml', 'config_check_html.yaml', 'run_check_html.csv')
    text = cfg.read_text(encoding='utf-8')
    text += '\n  check_report:\n    enabled: true\n    html_enabled: true\n'
    cfg.write_text(text, encoding='utf-8')
    artifacts = run_simulation(cfg, excel=False)
    assert artifacts.check_report_html_path is not None
    html_path = Path(artifacts.check_report_html_path)
    assert html_path.exists()
    html = html_path.read_text(encoding='utf-8')
    assert 'Last Cycle Check Report' in html
    assert 'mass_balance_residual_kg' in html


def test_last_cycle_check_report_contains_case_class_and_overall_status():
    _, cfg = _prepare_case('runner_check_report_csv', 'Projekte/config_1cyl_2t.yaml', 'config_check_case_class.yaml', 'run_check_case_class.csv')
    artifacts = run_simulation(cfg, excel=False)
    report_path = Path(artifacts.check_report_csv_path)
    text = report_path.read_text(encoding='utf-8')
    assert 'check_case_class' in text
    assert 'overall_status' in text
    assert 'mass_balance_residual_rel' in text
    assert 'energy_balance_residual_rel' in text


def test_last_cycle_check_report_contains_geometry_metrics_and_formatted_html():
    _, cfg = _prepare_case('runner_check_report_geometry', 'Projekte/config_1cyl_4t.yaml', 'config_check_geometry.yaml', 'run_check_geometry.csv')
    text_cfg = cfg.read_text(encoding='utf-8')
    text_cfg += '\n  check_report:\n    enabled: true\n    html_enabled: true\n'
    cfg.write_text(text_cfg, encoding='utf-8')
    artifacts = run_simulation(cfg, excel=False)
    report_text = Path(artifacts.check_report_csv_path).read_text(encoding='utf-8')
    assert 'bore_mm' in report_text
    assert 'stroke_mm' in report_text
    assert 'conrod_mm' in report_text
    assert 'bore_area_mm2' in report_text
    assert 'swept_cm3' in report_text
    assert 'clearance_cm3' in report_text
    assert 'lift_max_mm' in report_text
    assert 'A_ref_mm2' in report_text
    assert 'A_eff_forward_max_mm2' in report_text
    assert 'A_eff_reverse_max_mm2' in report_text
    html = Path(artifacts.check_report_html_path).read_text(encoding='utf-8')
    assert 'Geometrie' in html
    assert 'status-card' in html
    assert '>mg<' in html
    assert '>°C<' in html
    assert '>cm³<' in html
    assert '>mm<' in html
    assert '>mm²<' in html
    assert '>J<' in html
    assert '>bar<' in html
    assert '.0<' in html
