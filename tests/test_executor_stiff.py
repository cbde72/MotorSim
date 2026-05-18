from pathlib import Path

from thermo0d.input.config_loader import ConfigLoader
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.compute.executor import SimulationExecutor


def test_executor_runs_with_scipy_bdf_on_example(tmp_path):
    src = Path('Projekte/variants/config_1cyl_2t.yaml').read_text(encoding='utf-8')
    patched = src.replace('kind: scipy_rk45', 'kind: scipy_bdf')
    patched = patched.replace('csv_path: results/one_cyl_2t.csv', f'csv_path: {(tmp_path / "bdf.csv").as_posix()}')
    patched = patched.replace('total_cycles: 2', 'total_cycles: 1')
    patched = patched.replace('save_last_cycles: 1', 'save_last_cycles: 1')
    patched = patched.replace('dt_s: 0.00002', 'dt_s: 0.0001')
    data_dir = tmp_path / 'data'
    data_dir.mkdir()
    (data_dir / 'slot_cd_table.csv').write_text('0;0.8;0.8\n1;0.8;0.8\n', encoding='utf-8')
    cfg = tmp_path / 'config_bdf.yaml'
    cfg.write_text(patched, encoding='utf-8')
    config = ConfigLoader.load(cfg)
    bundle = build_model_bundle(config, cfg)
    result = SimulationExecutor(bundle).run()
    assert result.t.size > 10
    assert result.y.shape[1] == result.t.size
