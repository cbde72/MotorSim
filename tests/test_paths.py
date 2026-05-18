from pathlib import Path

from thermo0d.app.paths import PathManager


def test_path_manager_override(tmp_path: Path):
    previous = PathManager.settings()
    try:
        settings = PathManager.override(
            default_project=tmp_path / 'proj',
            default_test_space=tmp_path / 'tests',
            default_variants_dir=tmp_path / 'variants',
            project_root=tmp_path / 'root',
        )
        assert settings.default_project == (tmp_path / 'proj').resolve()
        assert settings.default_variants_dir == (tmp_path / 'variants').resolve()
        assert settings.project_root == (tmp_path / 'root').resolve()
    finally:
        PathManager.override(
            project_root=previous.project_root,
            default_project=previous.default_project,
            default_test_space=previous.default_test_space,
            default_variants_dir=previous.default_variants_dir,
        )


def test_default_output_dir_name_is_collision_safe_within_15_chars(tmp_path: Path):
    config_a = tmp_path / 'A156A1-2V-REX-V09d_WH02-Vibe_PP_RK45.yaml'
    config_b = tmp_path / 'A156A1-2V-REX-V09d_WH02-Vibe_PP_RK45_variant.yaml'
    name_a = PathManager.default_output_dir_name(config_a)
    name_b = PathManager.default_output_dir_name(config_b)
    assert len(name_a) <= 15
    assert len(name_b) <= 15
    assert name_a != name_b
    assert name_a.startswith('A156A1-2')
    assert name_b.startswith('A156A1-2')


def test_resolve_output_dir_uses_results_and_outdir_override(tmp_path: Path):
    config_path = tmp_path / 'demo_config.yaml'
    default_dir = PathManager.resolve_output_dir(config_path, None)
    custom_dir = PathManager.resolve_output_dir(config_path, 'custom_output_directory_name')
    assert default_dir == (tmp_path / 'results' / PathManager.default_output_dir_name(config_path)).resolve()
    assert custom_dir == (tmp_path / 'results' / PathManager.make_collision_safe_output_dir_name('custom_output_directory_name')).resolve()
    assert PathManager.resolve_results_dir(config_path, None) == (default_dir / 'results').resolve()
    assert PathManager.resolve_plots_dir(config_path, None) == (default_dir / 'plots').resolve()


def test_resolve_output_file_keeps_only_filename_inside_output_dir(tmp_path: Path):
    config_path = tmp_path / 'demo_config.yaml'
    resolved = PathManager.resolve_output_file(
        config_path,
        configured_outdir='custom_output_directory_name',
        configured_path='results/nested/out.csv',
        fallback_name='fallback.csv',
    )
    expected_dir = tmp_path / 'results' / PathManager.make_collision_safe_output_dir_name('custom_output_directory_name') / 'results'
    assert resolved == (expected_dir / 'out.csv').resolve()


def test_central_log_dir_points_to_test_cases_under_project_root(tmp_path: Path):
    previous = PathManager.settings()
    try:
        PathManager.override(project_root=tmp_path / 'project_root')
        assert PathManager.central_log_dir() == (tmp_path / 'project_root' / 'test_cases').resolve()
    finally:
        PathManager.override(
            project_root=previous.project_root,
            default_project=previous.default_project,
            default_test_space=previous.default_test_space,
            default_variants_dir=previous.default_variants_dir,
        )
