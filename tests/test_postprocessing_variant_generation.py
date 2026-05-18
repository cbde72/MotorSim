from __future__ import annotations

from pathlib import Path

import yaml

from thermo0d.app.postprocessing_variants import generate_postprocessing_variants


BASE_CONFIG = Path('Projekte/A156A1-2V-REX-V09d_WH02-Vibe_PP_RK45.yaml').resolve()
PROJECT_DIR = Path('Projekte').resolve()



def test_generate_postprocessing_variants_creates_named_configs_with_result_dirs(tmp_path: Path):
    out_dir = tmp_path / 'variants' / 'postprocessing'
    generated = generate_postprocessing_variants(BASE_CONFIG, project_dir=PROJECT_DIR, out_dir=out_dir)

    assert len(generated) >= 10
    first = yaml.safe_load(generated[0].read_text(encoding='utf-8'))
    assert str(first.get('test_description', '')).startswith('Postprocessing-Testvariante:')

    for config_path in generated:
        cfg = yaml.safe_load(config_path.read_text(encoding='utf-8'))
        variant_name = config_path.stem
        post = cfg['postprocessing']
        assert variant_name in str(post['csv_path'])
        assert variant_name in str(post['excel_path'])
        assert 'results' in str(post['csv_path'])
        assert 'plots' in str(post['plots']['output_dir'])
        assert len(variant_name) <= 64



def test_generated_variants_rewrite_relative_input_paths_to_new_variant_dir(tmp_path: Path):
    out_dir = tmp_path / 'variants' / 'postprocessing'
    generated = generate_postprocessing_variants(BASE_CONFIG, project_dir=PROJECT_DIR, out_dir=out_dir)
    cfg = yaml.safe_load(generated[0].read_text(encoding='utf-8'))

    intake_lift = cfg['preprocessing']['connections'][0]['lift_file']
    plot_layout = cfg['postprocessing']['plots']['layouts']['entries'][0]['path']

    assert (generated[0].parent / intake_lift).resolve().is_file()
    assert (generated[0].parent / plot_layout).resolve().is_file()
