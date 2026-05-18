from __future__ import annotations

from pathlib import Path

from thermo0d.app import cli



def test_main_dry_run_batch_postprocessing_variants(monkeypatch, tmp_path: Path):
    project = tmp_path / 'Projekte'
    project.mkdir()
    base = project / 'base.yaml'
    base.write_text('preprocessing: {volumes: [], connections: []}\nsimulation: {dt_s: 1.0, total_cycles: 1, save_last_cycles: 1, solver: {kind: rk4, rtol: 1.0, atol: 1.0}}\npostprocessing: {sampling: {mode: time, step_s: 1.0}}\n', encoding='utf-8')

    generated_dir = project / 'variants' / 'postprocessing'
    generated = [generated_dir / 'a.yaml', generated_dir / 'b.yaml']
    for path in generated:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('x: 1\n', encoding='utf-8')

    monkeypatch.setattr(
        cli,
        'generate_postprocessing_variants',
        lambda *args, **kwargs: generated,
    )
    called: list[tuple[Path, object]] = []
    monkeypatch.setattr(cli, 'run_simulation', lambda p, excel=None: called.append((Path(p), excel)))

    rc = cli.main([
        '--project', str(project),
        '--config', str(base),
        '--batch-postprocessing-variants',
        '--dry-run',
    ])
    assert rc == 0
    assert called == []
