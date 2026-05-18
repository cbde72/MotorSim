from __future__ import annotations

import math
from pathlib import Path

import pytest

from thermo0d.input.config_loader import ConfigLoader
from thermo0d.input.model_builder import build_model_bundle


def test_free_piston_mechanics_can_be_defined_by_diameter_and_compression_ratio() -> None:
    cfg = ConfigLoader.load(Path('Projekte/variants/free_piston_vibe_generator.yaml'))
    assert cfg.free_piston is not None
    mech = cfg.free_piston.mechanics
    assert mech.piston_diameter_m == pytest.approx(0.07450721049029624)
    assert mech.compression_ratio == pytest.approx(43.728)
    assert mech.derived_piston_area_m2 == pytest.approx(0.00436)
    assert mech.derived_clearance_volume_m3 == pytest.approx(8.16326530612245e-06)


def test_free_piston_bundle_uses_derived_geometry_from_new_inputs() -> None:
    cfg_path = Path('Projekte/variants/free_piston_vibe_generator.yaml')
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    assert bundle.free_piston is not None
    assert bundle.free_piston.piston_diameter_m == pytest.approx(0.07450721049029624)
    assert bundle.free_piston.compression_ratio == pytest.approx(43.728)
    assert bundle.free_piston.piston_area_m2 == pytest.approx(0.00436)
    assert bundle.free_piston.clearance_volume_m3 == pytest.approx(8.16326530612245e-06)


def test_free_piston_legacy_geometry_input_is_still_supported(tmp_path: Path) -> None:
    cfg_text = """
modeling:
  architecture: free_piston
free_piston:
  initial_conditions:
    x0_m: 0.04
    v0_m_per_s: -1.0
    cylinder:
      pressure_Pa: 120000.0
      temperature_K: 300.0
    bounce:
      pressure_Pa: 180000.0
      temperature_K: 300.0
  mechanics:
    moving_mass_kg: 0.7
    piston_area_m2: 0.00436
    clearance_volume_m3: 8.16326530612245e-06
    x_min_m: 0.0
    x_max_m: 0.08
  friction:
    model: coulomb_viscous
    fc_N: 0.0
    cv_Ns_per_m: 0.0
  load:
    model: none
    damping_Ns_per_m: 0.0
  bounce:
    model: gas_spring
    chamber_volume0_m3: 0.0002
    p0_Pa: 300000.0
    polytropic_exponent: 1.28
preprocessing:
  gas_properties:
    cp_J_per_kgK: 1005.0
    cv_J_per_kgK: 718.0
    R_J_per_kgK: 287.0
  features:
    mass_flow: false
    wall_heat: false
    combustion: false
    evaporation: false
    pv_work: false
  engine:
    cycle_type: 2t
    speed_rpm: 25.0
  volumes:
    - name: cylinder
      type: cylinder
      initial_pressure_Pa: 120000.0
      initial_temperature_K: 300.0
      kinematics:
        type: crank_slider
        bore_m: 0.0745
        stroke_m: 0.08
        conrod_m: 0.12
        compression_ratio: 43.728
        phase_deg: 0.0
      wall_heat:
        model: none
      combustion:
        model: none
      evaporation:
        model: none
  connections: []
simulation:
  dt_s: 1.0e-05
  total_cycles: 1
  save_last_cycles: 1
  simulationtime: 0.001
  solver:
    kind: rk4
    rtol: 1.0e-06
    atol: 1.0e-09
postprocessing:
  csv_enabled: false
  csv_path: results/out.csv
  excel_enabled: false
  excel_path: results/out.xlsx
  sampling:
    mode: time
    step_s: 0.0001
"""
    cfg_path = tmp_path / 'legacy_fp.yaml'
    cfg_path.write_text(cfg_text, encoding='utf-8')
    cfg = ConfigLoader.load(cfg_path)
    mech = cfg.free_piston.mechanics
    assert mech.derived_piston_diameter_m == pytest.approx(math.sqrt(4.0 * 0.00436 / math.pi))
    assert mech.derived_compression_ratio == pytest.approx(43.728)


def test_free_piston_bounce_can_be_defined_in_preprocessing_volumes() -> None:
    cfg = ConfigLoader.load(Path('Projekte/variants/free_piston_vibe_generator.yaml'))
    bounce = next(vol for vol in cfg.preprocessing.volumes if getattr(vol, 'type', None) == 'bounce_chamber')
    assert bounce.chamber_diameter_m == pytest.approx(0.07450721049029624)
    assert bounce.chamber_length_m == pytest.approx(0.08)
    assert bounce.compression_ratio == pytest.approx(2.5854545454545454)
    assert bounce.derived_swept_volume_m3 == pytest.approx(0.0003488)
    assert bounce.derived_chamber_min_volume_m3 == pytest.approx(0.00022)
    assert bounce.derived_chamber_volume0_m3 == pytest.approx(0.0005688)


def test_free_piston_bundle_uses_derived_bounce_geometry_from_new_inputs() -> None:
    cfg_path = Path('Projekte/variants/free_piston_vibe_generator.yaml')
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    assert bundle.free_piston is not None
    assert bundle.free_piston.bounce_chamber_diameter_m == pytest.approx(0.07450721049029624)
    assert bundle.free_piston.bounce_chamber_length_m == pytest.approx(0.08)
    assert bundle.free_piston.bounce_compression_ratio == pytest.approx(2.5854545454545454)
    assert bundle.free_piston.bounce_chamber_cross_section_m2 == pytest.approx(0.00436)
    assert bundle.free_piston.bounce_swept_volume_m3 == pytest.approx(0.0003488)
    assert bundle.free_piston.bounce_area_m2 == pytest.approx(0.00436)
    assert bundle.free_piston.bounce_chamber_min_volume_m3 == pytest.approx(0.00022)
    assert bundle.free_piston.bounce_chamber_volume0_m3 == pytest.approx(0.0005688)


def test_free_piston_bounce_volume_is_maximum_at_ot_and_runs_opposite_to_cylinder() -> None:
    from thermo0d.model.free_piston.geometry import bounce_volume_from_position
    cfg = ConfigLoader.load(Path('Projekte/variants/free_piston_vibe_generator.yaml'))
    bundle = build_model_bundle(cfg, Path('Projekte/variants/free_piston_vibe_generator.yaml'))
    fp = bundle.free_piston
    assert fp is not None
    v_ot = bounce_volume_from_position(fp.bounce_chamber_volume0_m3, fp.bounce_area_m2, fp.x_min_m, fp.x_min_m, fp.x_max_m)
    v_ut = bounce_volume_from_position(fp.bounce_chamber_volume0_m3, fp.bounce_area_m2, fp.x_max_m, fp.x_min_m, fp.x_max_m)
    assert v_ot == pytest.approx(fp.bounce_chamber_volume0_m3)
    assert v_ut == pytest.approx(fp.bounce_chamber_min_volume_m3)
    assert v_ut < v_ot
    assert v_ut == pytest.approx(fp.bounce_chamber_volume0_m3 - fp.bounce_area_m2 * (fp.x_max_m - fp.x_min_m))


def test_bounce_reference_pressure_is_derived_from_initial_pressure_when_omitted() -> None:
    cfg_path = Path('Projekte/variants/free_piston_vibe_generator.yaml')
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    assert bundle.free_piston is not None
    fp = bundle.free_piston
    from thermo0d.model.free_piston.geometry import bounce_volume_from_position
    v0 = bounce_volume_from_position(fp.bounce_chamber_volume0_m3, fp.bounce_area_m2, fp.x0_m, fp.x_min_m, fp.x_max_m)
    expected_p0 = fp.bounce_pressure_Pa / ((fp.bounce_chamber_volume0_m3 / v0) ** fp.bounce_polytropic_exponent)
    assert fp.bounce_p0_Pa == pytest.approx(expected_p0)


def test_explicit_bounce_p0_is_ignored_in_favour_of_initial_pressure_start_state(tmp_path: Path) -> None:
    cfg_text = Path('Projekte/variants/free_piston_vibe_generator.yaml').read_text(encoding='utf-8')
    cfg_text = cfg_text.replace('    compression_ratio: 2.5854545454545454\n', '    compression_ratio: 2.5854545454545454\n    p0_Pa: 360000.0\n', 1)
    cfg_path = tmp_path / 'legacy_bounce_p0.yaml'
    cfg_path.write_text(cfg_text, encoding='utf-8')
    cfg = ConfigLoader.load(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    assert bundle.free_piston is not None
    fp = bundle.free_piston
    from thermo0d.model.free_piston.geometry import bounce_volume_from_position
    v0 = bounce_volume_from_position(fp.bounce_chamber_volume0_m3, fp.bounce_area_m2, fp.x0_m, fp.x_min_m, fp.x_max_m)
    expected_p0 = fp.bounce_pressure_Pa / ((fp.bounce_chamber_volume0_m3 / v0) ** fp.bounce_polytropic_exponent)
    assert fp.bounce_p0_Pa == pytest.approx(expected_p0)
    assert fp.bounce_p0_Pa != pytest.approx(360000.0)


