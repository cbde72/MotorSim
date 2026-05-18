from __future__ import annotations

from pathlib import Path

import pytest

from thermo0d.app import cli
from thermo0d.input.config_loader import ConfigLoadError, load_config


def test_pydantic_validation_error_is_pretty_formatted(tmp_path: Path):
    text = Path('Projekte/config_1cyl_2t.yaml').read_text(encoding='utf-8')
    text = text.replace('step_deg: 5.0', 'step_deg: 0.0')
    cfg_path = tmp_path / 'bad_angle.yaml'
    cfg_path.write_text(text, encoding='utf-8')

    with pytest.raises(ConfigLoadError) as excinfo:
        load_config(cfg_path)

    message = str(excinfo.value)
    assert 'KONFIGURATIONS-VALIDIERUNG FEHLGESCHLAGEN' in message
    assert str(cfg_path.resolve()) in message
    assert 'postprocessing.sampling.crank_angle' in message
    assert 'step_deg must be > 0' in message
    assert 'Bitte Feldnamen, Pflichtfelder, Datentypen und Wertebereiche' in message



def test_cli_returns_2_and_prints_pretty_config_error(monkeypatch, tmp_path: Path, capsys):
    project = tmp_path / 'Projekte'
    project.mkdir()
    cfg = project / 'config.yaml'
    cfg.write_text('simulation: {}', encoding='utf-8')

    pretty = 'KONFIGURATIONS-VALIDIERUNG FEHLGESCHLAGEN\n[1] Feld    : simulation.dt_s'

    def fake_run(*args, **kwargs):
        raise ConfigLoadError(cfg, pretty, kind='pydantic_validation_error')

    monkeypatch.setattr(cli, 'run_simulation', fake_run)
    rc = cli.main(['--project', str(project)])
    err = capsys.readouterr().err

    assert rc == 2
    assert 'KONFIGURATIONS-VALIDIERUNG FEHLGESCHLAGEN' in err
    assert 'simulation.dt_s' in err
