from pathlib import Path


def test_config_tool_supports_validate_upgrade_normalize_explain_and_diff() -> None:
    text = Path('scripts/config_tool.py').read_text(encoding='utf-8')
    assert 'add_parser("validate"' in text or "add_parser('validate'" in text
    assert 'add_parser("upgrade"' in text or "add_parser('upgrade'" in text
    assert 'add_parser("normalize"' in text or "add_parser('normalize'" in text
    assert 'add_parser("explain"' in text or "add_parser('explain'" in text
    assert 'add_parser("diff"' in text or "add_parser('diff'" in text
    assert 'migrate_config_data' in text
    assert 'normalize_config_data' in text
    assert 'RootConfig.model_validate' in text or '_validated_without_versioning' in text


def test_master_reference_config_exists() -> None:
    text = Path('Projekte/variants/config_master_reference.yaml').read_text(encoding='utf-8')
    assert 'config_schema_version: 5' in text
    assert 'final_cycle_uniform_angle_export:' in text
    assert 'simulation:' in text
    assert 'postprocessing:' in text
