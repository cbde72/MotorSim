from pathlib import Path

import pytest

from thermo0d.config.models import load_config
from thermo0d.config_versioning import migrate_config_data


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


def test_volume_submodel_refs_resolve_to_central_definitions() -> None:
    cfg = load_config(Path('Projekte/variants/free_piston_GenSet_V13.yaml'))
    cylinder_1, cylinder_2 = cfg.preprocessing.volumes[:2]

    assert getattr(cylinder_1.wall_heat, 'model', None) == 'woschni'
    assert getattr(cylinder_2.wall_heat, 'model', None) == 'woschni'
    assert getattr(cylinder_1.combustion, 'model', None) == 'vibe'
    assert getattr(cylinder_2.combustion, 'model', None) == 'vibe'
    assert cylinder_1.combustion.hign_mm == 10.0
    assert cylinder_1.combustion.duration_ms == 6.0
    assert cylinder_2.combustion.hign_mm == 20.0
    assert cylinder_2.combustion.duration_ms == 3.0


def test_unknown_volume_submodel_ref_fails_clearly(tmp_path: Path) -> None:
    text = Path('Projekte/variants/free_piston_GenSet_V13.yaml').read_text(encoding='utf-8')
    text = text.replace('ref: vibe_lambda_slot', 'ref: missing_vibe', 1)
    cfg_path = tmp_path / 'bad_submodel_ref.yaml'
    cfg_path.write_text(text, encoding='utf-8')

    with pytest.raises(Exception, match='missing_vibe'):
        load_config(cfg_path)


def test_submodel_library_does_not_inject_none_blocks_into_unreferenced_volumes() -> None:
    migrated = migrate_config_data(
        {
            'versioning': {'config_schema_version': 6},
            'preprocessing': {
                'submodels': {
                    'wall_heat': {'wall_ref': {'model': 'none'}},
                    'combustion': {'combustion_ref': {'model': 'none'}},
                },
                'volumes': [
                    {
                        'name': 'cylinder_1',
                        'type': 'cylinder',
                        'wall_heat': {'ref': 'wall_ref'},
                        'combustion': {'ref': 'combustion_ref'},
                    },
                    {'name': 'compressor_1', 'type': 'bounce_chamber'},
                    {'name': 'ambient_in', 'type': 'environment'},
                ],
            },
        }
    )
    volumes = migrated['preprocessing']['volumes']

    assert volumes[0]['wall_heat'] == {'model': 'none'}
    assert volumes[0]['combustion'] == {'model': 'none'}
    assert 'wall_heat' not in volumes[1]
    assert 'combustion' not in volumes[1]
    assert 'wall_heat' not in volumes[2]
    assert 'combustion' not in volumes[2]


def test_volume_refs_resolve_before_nested_submodel_refs() -> None:
    migrated = migrate_config_data(
        {
            'versioning': {'config_schema_version': 6},
            'preprocessing': {
                'submodels': {
                    'volumes': {
                        'shared_cylinder': {
                            'type': 'cylinder',
                            'kinematics': {
                                'type': 'crank_slider',
                                'bore_m': 0.08,
                                'stroke_m': 0.09,
                                'conrod_m': 0.14,
                                'compression_ratio': 12.0,
                                'phase_deg': 0.0,
                            },
                            'wall_heat': {'ref': 'wall_ref'},
                            'combustion': {'ref': 'combustion_ref'},
                            'evaporation': {'model': 'none'},
                        },
                    },
                    'wall_heat': {'wall_ref': {'model': 'none'}},
                    'combustion': {'combustion_ref': {'model': 'none'}},
                },
                'volumes': [
                    {
                        'name': 'cylinder_1',
                        'ref': 'shared_cylinder',
                        'initial_pressure_Pa': 100000.0,
                        'initial_temperature_K': 300.0,
                    },
                ],
            },
        }
    )
    volume = migrated['preprocessing']['volumes'][0]

    assert volume['type'] == 'cylinder'
    assert volume['name'] == 'cylinder_1'
    assert volume['kinematics']['bore_m'] == 0.08
    assert volume['wall_heat'] == {'model': 'none'}
    assert volume['combustion'] == {'model': 'none'}
    assert volume['initial_pressure_Pa'] == 100000.0


def test_unknown_volume_ref_fails_clearly() -> None:
    with pytest.raises(ValueError, match='missing_volume'):
        migrate_config_data(
            {
                'versioning': {'config_schema_version': 6},
                'preprocessing': {
                    'submodels': {'volumes': {}},
                    'volumes': [{'name': 'cylinder_1', 'ref': 'missing_volume'}],
                },
            }
        )


def test_connection_refs_resolve_to_central_definitions() -> None:
    migrated = migrate_config_data(
        {
            'versioning': {'config_schema_version': 6},
            'preprocessing': {
                'submodels': {
                    'connections': {
                        'shared_orifice': {
                            'type': 'orifice',
                            'diameter_mm': 14.0,
                            'forward_cd': 0.98,
                            'reverse_cd': 0.98,
                        },
                    },
                },
                'connections': [
                    {
                        'name': 'bleed_1',
                        'ref': 'shared_orifice',
                        'from_volume': 'plenum_1',
                        'to_volume': 'ambient',
                    },
                    {
                        'name': 'bleed_2',
                        'ref': 'shared_orifice',
                        'from_volume': 'plenum_2',
                        'to_volume': 'ambient',
                        'reverse_cd': 0.9,
                    },
                ],
            },
        }
    )
    connections = migrated['preprocessing']['connections']

    assert connections[0] == {
        'type': 'orifice',
        'diameter_mm': 14.0,
        'forward_cd': 0.98,
        'reverse_cd': 0.98,
        'name': 'bleed_1',
        'from_volume': 'plenum_1',
        'to_volume': 'ambient',
    }
    assert connections[1]['type'] == 'orifice'
    assert connections[1]['forward_cd'] == 0.98
    assert connections[1]['reverse_cd'] == 0.9


def test_unknown_connection_ref_fails_clearly() -> None:
    with pytest.raises(ValueError, match='missing_connection'):
        migrate_config_data(
            {
                'versioning': {'config_schema_version': 6},
                'preprocessing': {
                    'submodels': {'connections': {}},
                    'connections': [
                        {
                            'name': 'bleed',
                            'ref': 'missing_connection',
                            'from_volume': 'plenum',
                            'to_volume': 'ambient',
                        },
                    ],
                },
            }
        )


def test_hcci_diesel_combustion_config_loads_from_central_submodel(tmp_path: Path) -> None:
    text = Path('Projekte/variants/free_piston_GenSet_V14.yaml').read_text(encoding='utf-8')
    text = text.replace('ref: vibe_lambda_slot', 'ref: hcci_diesel_default', 1)
    cfg_path = tmp_path / 'hcci_active.yaml'
    cfg_path.write_text(text, encoding='utf-8')

    cfg = load_config(cfg_path)
    hcci = cfg.preprocessing.volumes[0].combustion

    assert hcci.model == 'hcci_diesel'
    assert hcci.ignition_model == 'livengood_wu'
    assert hcci.burn_model == 'wiebe_autoignition'
    assert hcci.duration_ms == 1.2
    assert hcci.lambda_target == 1.4
