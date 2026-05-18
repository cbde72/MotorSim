from pathlib import Path

import pytest

from thermo0d.config.models import load_config


def test_load_config_reads_separated_sections_and_sampling_modes():
    cfg_4t = load_config(Path('Projekte/config_1cyl_4t.yaml'))
    assert cfg_4t.preprocessing.engine.cycle_type == '4t'
    assert cfg_4t.simulation.dt_s > 0.0
    assert cfg_4t.postprocessing.sampling.mode == 'crank_angle'
    assert cfg_4t.postprocessing.sampling.step_deg > 0.0

    cfg_2t = load_config(Path('Projekte/config_1cyl_2t.yaml'))
    assert cfg_2t.preprocessing.engine.cycle_type == '2t'
    assert cfg_2t.postprocessing.sampling.mode == 'crank_angle'
    assert cfg_2t.postprocessing.sampling.step_deg > 0.0


def test_time_based_output_step_must_not_be_smaller_than_dt(tmp_path: Path):
    text = Path('Projekte/config_1cyl_4t.yaml').read_text(encoding='utf-8')
    text = text.replace('mode: crank_angle', 'mode: time')
    text = text.replace('step_deg: 1.0', 'step_s: 0.000001')
    cfg_path = tmp_path / 'bad.yaml'
    cfg_path.write_text(text, encoding='utf-8')
    with pytest.raises(Exception):
        load_config(cfg_path)


def test_angle_based_output_step_must_be_positive(tmp_path: Path):
    text = Path('Projekte/config_1cyl_2t.yaml').read_text(encoding='utf-8')
    text = text.replace('step_deg: 5.0', 'step_deg: 0.0')
    cfg_path = tmp_path / 'bad_angle.yaml'
    cfg_path.write_text(text, encoding='utf-8')
    with pytest.raises(Exception):
        load_config(cfg_path)


def test_disabled_evaporation_config_accepts_legacy_hidden_angle_reference(tmp_path: Path):
    text = Path('Projekte/config_1cyl_2t.yaml').read_text(encoding='utf-8')
    needle = '      evaporation:\n        model: none'
    replacement = '      evaporation:\n        model: none\n        angle_reference: absolute'
    assert needle in text
    text = text.replace(needle, replacement, 1)
    cfg_path = tmp_path / 'legacy_hidden_evap.yaml'
    cfg_path.write_text(text, encoding='utf-8')
    cfg = load_config(cfg_path)
    assert any(getattr(v.evaporation, 'model', None) == 'none' for v in cfg.preprocessing.volumes)


def test_disabled_wall_heat_config_accepts_legacy_hidden_fields(tmp_path: Path):
    text = Path('Projekte/config_1cyl_2t.yaml').read_text(encoding='utf-8')
    needle = '      wall_heat:\n        model: none'
    replacement = '      wall_heat:\n        model: none\n        c1: 2.28\n        c2: 0.00324\n        c3: 0.0\n        wall_temperature_K: 450.0\n        wall_area_m2: 0.01'
    assert needle in text
    text = text.replace(needle, replacement, 1)
    cfg_path = tmp_path / 'legacy_hidden_wall_heat.yaml'
    cfg_path.write_text(text, encoding='utf-8')
    cfg = load_config(cfg_path)
    assert any(getattr(v.wall_heat, 'model', None) == 'none' for v in cfg.preprocessing.volumes)
