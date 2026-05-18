from pathlib import Path

from thermo0d.input.config_loader import ConfigLoader
from thermo0d.input.model_builder import MatrixModelBuilder, build_model_bundle
from thermo0d.model.conventional.builder import build_conventional_bundle


def test_conventional_builder_module_builds_classic_bundle() -> None:
    cfg_path = Path('Projekte/config_1cyl_4t.yaml').resolve()
    cfg = ConfigLoader.load(cfg_path)
    builder = MatrixModelBuilder(cfg, cfg_path)

    bundle = build_conventional_bundle(builder)

    assert bundle.architecture == 'classic'
    assert bundle.state_layout is not None
    assert bundle.state_layout.has_free_piston_states is False


def test_default_dispatch_uses_conventional_architecture() -> None:
    cfg_path = Path('Projekte/config_1cyl_4t.yaml').resolve()
    cfg = ConfigLoader.load(cfg_path)

    bundle = build_model_bundle(cfg, cfg_path)

    assert cfg.modeling.architecture == 'classic'
    assert bundle.architecture == 'classic'
