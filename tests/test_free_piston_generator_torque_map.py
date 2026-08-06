from pathlib import Path
from types import SimpleNamespace

import numpy as np

from thermo0d.config.models import load_config
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.model.free_piston.generator_map import _read_cache, generator_map_cache_path, load_generator_torque_map, lookup_generator_torque_map
from thermo0d.model.free_piston.rhs import compute_free_piston_rhs


CONFIG_PATH = Path("Projekte/variants/free_piston_GenSet_V57.yaml")


def test_v57_generator_torque_map_loads_all_resistance_sheets() -> None:
    config = load_config(CONFIG_PATH)
    bundle = build_model_bundle(config, CONFIG_PATH)
    generator_map = bundle.free_piston.generator_torque_map

    assert config.free_piston.load.model == "generator_torque_map"
    np.testing.assert_allclose(generator_map.resistances_ohm, [0.3, 0.5, 1.0, 2.0, 5.0, 10.0])


def test_v57_angle_mapping_and_direction_follow_rotor_1() -> None:
    config = load_config(CONFIG_PATH)
    bundle = build_model_bundle(config, CONFIG_PATH)
    fp = bundle.free_piston
    generator_map = fp.generator_torque_map

    at_x_min = lookup_generator_torque_map(generator_map, fp.rotary_angle_min_rad, 1.0, fp.rotary_angle_min_rad, fp.rotary_angle_max_rad)
    at_mid = lookup_generator_torque_map(generator_map, 0.5 * (fp.rotary_angle_min_rad + fp.rotary_angle_max_rad), 1.0, fp.rotary_angle_min_rad, fp.rotary_angle_max_rad)
    at_x_max = lookup_generator_torque_map(generator_map, fp.rotary_angle_max_rad, 1.0, fp.rotary_angle_min_rad, fp.rotary_angle_max_rad)

    assert at_x_min.angle_deg == 9.0
    assert abs(at_mid.angle_deg) < 1.0e-12
    assert at_x_max.angle_deg == -9.0
    assert not at_mid.out_of_range


def test_v57_initial_rhs_with_generator_map_is_finite() -> None:
    config = load_config(CONFIG_PATH)
    bundle = build_model_bundle(config, CONFIG_PATH)
    derivative = compute_free_piston_rhs(0.0, bundle.y_init.copy(), bundle)

    assert derivative.shape == bundle.y_init.shape
    assert np.all(np.isfinite(derivative))


def _map_config(filename: str) -> SimpleNamespace:
    return SimpleNamespace(
        file=filename,
        load_resistance_ohm=1.0,
        angle_at_x_min_deg=9.0,
        angle_at_x_max_deg=-9.0,
        include_no_load_torque=True,
        angle_out_of_range="clamp",
        resistance_out_of_range="error",
        max_abs_torque_Nm=1800.0,
        max_electrical_power_W=25000.0,
    )


def test_generator_map_cache_is_reused_until_excel_content_changes(monkeypatch) -> None:
    import openpyxl

    source = Path("Projekte/A16-002-28c_TorqueToWork_Spa_V01.xlsx").resolve()
    run_config = Path("Projekte/variants/free_piston_GenSet_V57.yaml").resolve()
    config = _map_config(str(source))

    first = load_generator_torque_map(config, run_config)
    cache = generator_map_cache_path(source)
    first_timestamp = cache.stat().st_mtime_ns

    def fail_if_excel_is_loaded(*args, **kwargs):
        raise AssertionError("unchanged workbook must be loaded from NPZ cache")

    monkeypatch.setattr(openpyxl, "load_workbook", fail_if_excel_is_loaded)
    second = load_generator_torque_map(config, run_config)

    assert cache.stat().st_mtime_ns == first_timestamp
    np.testing.assert_allclose(first.resistances_ohm, second.resistances_ohm)
    assert _read_cache(cache, "changed-excel-content-hash") is None
