from pathlib import Path
from types import SimpleNamespace

from thermo0d.app.paths import PathManager
from thermo0d.input.config_resolver import ConfigResolver
from thermo0d.app.cli import _append_fail_log, _append_run_log, parse_args


PROJECT_DIR = Path('Projekte').resolve()


def test_parse_args_accepts_excel_and_project():
    args = parse_args(['--project', 'Projekte', '--config', 'config.yaml', '--excel'])
    assert args.project == 'Projekte'
    assert args.config == 'config.yaml'
    assert args.excel is True


def test_resolve_config_from_project_dir():
    resolver = ConfigResolver(PROJECT_DIR, PROJECT_DIR / 'variants')
    resolved = resolver.resolve_single_config('config_1cyl_2t.yaml', PROJECT_DIR)
    assert resolved == (PROJECT_DIR / 'config_1cyl_2t.yaml').resolve()


def test_resolve_batch_variants():
    resolver = ConfigResolver(PROJECT_DIR, PROJECT_DIR / 'variants')
    paths = resolver.resolve_batch_configs(PROJECT_DIR / 'variants')
    assert len(paths) >= 2


def test_run_and_fail_logs_stay_central_under_test_cases(tmp_path: Path):
    project_root = tmp_path / 'project_root'
    previous = PathManager.settings()
    try:
        PathManager.override(project_root=project_root)

        artifacts = SimpleNamespace(
            cycle_summaries=[SimpleNamespace(
                cycle_index=3,
                air_mass_mg=123.456,
                runtime_s=0.0123,
                piston_work_J=45.6,
                pmax_bar=12.34,
            )],
            wall_clock_s=0.5,
            bundle=None,
        )
        config_path = str((tmp_path / 'work' / 'demo_config.yaml').resolve())
        _append_run_log(config_path, artifacts)
        _append_fail_log(config_path, RuntimeError('boom'))

        run_log = project_root / 'test_cases' / 'run.log'
        fail_log = project_root / 'test_cases' / 'fail.log'
        assert run_log.exists()
        assert fail_log.exists()
        assert 'demo_config.yaml' in run_log.read_text(encoding='utf-8')
        assert 'RuntimeError: boom' in fail_log.read_text(encoding='utf-8')
    finally:
        PathManager.override(
            project_root=previous.project_root,
            default_project=previous.default_project,
            default_test_space=previous.default_test_space,
            default_variants_dir=previous.default_variants_dir,
        )
