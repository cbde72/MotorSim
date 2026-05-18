from __future__ import annotations

import sys
from pathlib import Path

import pytest

from thermo0d.app import cli


def test_main_dry_run_batch_and_continue(monkeypatch, tmp_path: Path):
    project = tmp_path / 'Projekte'
    variants = project / 'variants'
    variants.mkdir(parents=True)
    (variants / 'a.yaml').write_text('x: 1', encoding='utf-8')
    (variants / 'b.yaml').write_text('x: 2', encoding='utf-8')

    called: list[tuple[Path, object]] = []
    monkeypatch.setattr(cli, 'run_simulation', lambda p, excel=None: called.append((Path(p), excel)))
    rc = cli.main([
        '--project', str(project),
        '--variants-dir', str(variants),
        '--batch-variants',
        '--dry-run',
        '--continue-on-error',
        '--excel',
    ])
    assert rc == 0
    assert called == []


def test_main_continue_on_error(monkeypatch, tmp_path: Path, capsys):
    project = tmp_path / 'Projekte'
    variants = project / 'variants'
    variants.mkdir(parents=True)
    a = variants / 'a.yaml'
    b = variants / 'b.yaml'
    a.write_text('x: 1', encoding='utf-8')
    b.write_text('x: 2', encoding='utf-8')

    def fake_run(path, excel=None):
        if Path(path).name == 'a.yaml':
            raise RuntimeError('boom')
        return None

    monkeypatch.setattr(cli, 'run_simulation', fake_run)
    rc = cli.main([
        '--project', str(project),
        '--variants-dir', str(variants),
        '--batch-variants',
        '--continue-on-error',
    ])
    err = capsys.readouterr().err
    assert rc == 1
    assert 'Variante fehlgeschlagen' in err


def test_main_raises_without_continue(monkeypatch, tmp_path: Path):
    project = tmp_path / 'Projekte'
    project.mkdir()
    cfg = project / 'config.yaml'
    cfg.write_text('x: 1', encoding='utf-8')
    monkeypatch.setattr(cli, 'run_simulation', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('boom')))
    with pytest.raises(RuntimeError):
        cli.main(['--project', str(project)])


def test_run_uses_sys_argv(monkeypatch):
    monkeypatch.setattr(cli, 'main', lambda args=None: 7)
    monkeypatch.setattr(sys, 'argv', ['run_simulation.py', '--dry-run'])
    assert cli.run() == 7
