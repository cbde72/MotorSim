from pathlib import Path

import numpy as np
import yaml

from thermo0d.input.config_loader import ConfigLoader
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.model.free_piston.combustion_latch import _hcci_accumulation_window_active, free_piston_uses_hcci_diesel
from thermo0d.output.reconstruction import SignalReconstructionService


def test_vibe_hcci_diagnostics_do_not_enable_autoignition_rhs() -> None:
    config_path = Path("Projekte/variants/free_piston_GenSet_V25.yaml")
    cfg = ConfigLoader.load(config_path)
    bundle = build_model_bundle(cfg, config_path)
    fp = bundle.free_piston

    assert fp is not None
    assert not np.any(fp.hcci_enabled_by_vol)
    assert np.any(fp.hcci_diagnostics_enabled_by_vol)
    assert np.any(fp.hcci_accumulation_start_mode_by_vol == 1)
    assert np.isclose(float(np.max(fp.hcci_accumulation_start_distance_from_tdc_by_vol_m)), 0.03)
    assert np.any(fp.hcci_accumulation_end_mode_by_vol == 1)
    assert not free_piston_uses_hcci_diesel(bundle)


def test_vibe_hcci_diagnostics_ref_can_target_ignition_submodel(tmp_path: Path) -> None:
    config_path = Path("Projekte/variants/free_piston_GenSet_V32.yaml")
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    combustion_library = raw["preprocessing"]["submodels"]["combustion"]
    combustion_library.pop("hcci_diag_beck_2003_1_arrhenius", None)

    def replace_diag_ref(obj):
        if isinstance(obj, dict):
            if obj.get("hcci_diagnostics_ref") == "hcci_diag_beck_2003_1_arrhenius":
                obj["hcci_diagnostics_ref"] = "ignition_diag_beck_2003_1_arrhenius"
            for value in obj.values():
                replace_diag_ref(value)
        elif isinstance(obj, list):
            for value in obj:
                replace_diag_ref(value)

    replace_diag_ref(raw)
    tmp_config = tmp_path / "vibe_ignition_diag_ref.yaml"
    tmp_config.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True), encoding="utf-8")

    cfg = ConfigLoader.load(tmp_config)
    bundle = build_model_bundle(cfg, tmp_config)
    fp = bundle.free_piston

    assert fp is not None
    assert not np.any(fp.hcci_enabled_by_vol)
    assert np.any(fp.hcci_diagnostics_enabled_by_vol)
    assert np.any(fp.hcci_ignition_model_by_vol == 1)


def test_vibe_hcci_diagnostics_export_unbounded_integral_aliases() -> None:
    config_path = Path("Projekte/variants/free_piston_GenSet_V25.yaml")
    cfg = ConfigLoader.load(config_path)
    bundle = build_model_bundle(cfg, config_path)
    t = np.asarray([0.0, 1.0e-4], dtype=np.float64)
    y = np.column_stack([bundle.y_init, bundle.y_init])
    cycle_indices = np.zeros(t.shape[0], dtype=np.int64)

    columns = SignalReconstructionService.build(bundle, t, y, cycle_indices).columns

    assert "cylinder_1_hcci_ignition_delay_s" in columns
    assert "cylinder_1_hcci_ignition_integral" in columns
    assert "cylinder_1_hcci_ignition_integral_0to1" in columns
    assert "cylinder_1_hcci_validity_reason_code" in columns
    assert "cylinder_1_hcci_accumulation_window_active_0to1" in columns
    assert "cylinder_1_hcci_start_temperature_min_K" in columns
    assert "cylinder_1_hcci_start_pressure_min_Pa" in columns
    assert "cylinder_1_hcci_lambda" in columns
    assert "cylinder_1_hcci_residual_fraction_0to1" in columns
    assert "cylinder_1_hcci_tabulated_out_of_bounds_0to1" in columns


def test_vibe_hcci_diagnostics_window_uses_reconstructed_combustion_end() -> None:
    config_path = Path("Projekte/variants/free_piston_GenSet_V25.yaml")
    cfg = ConfigLoader.load(config_path)
    bundle = build_model_bundle(cfg, config_path)
    fp = bundle.free_piston

    assert fp is not None
    cyl = int(bundle.cylinder_indices[0])
    x_m = float(fp.x_min_m + 0.5 * fp.hcci_accumulation_start_distance_from_tdc_by_vol_m[cyl])
    v_m_per_s = -1.0

    assert _hcci_accumulation_window_active(
        bundle,
        cyl,
        x_m,
        v_m_per_s,
        combustion_fraction_0to1=0.5,
    )
    assert not _hcci_accumulation_window_active(
        bundle,
        cyl,
        x_m,
        v_m_per_s,
        combustion_fraction_0to1=1.0,
    )


def test_v37_is_diagnostic_only_with_cylinder_specific_lw_fits() -> None:
    config_path = Path("Projekte/variants/free_piston_GenSet_V37.yaml")
    cfg = ConfigLoader.load(config_path)
    bundle = build_model_bundle(cfg, config_path)
    fp = bundle.free_piston

    assert fp is not None
    assert not np.any(fp.hcci_enabled_by_vol)
    assert np.all(fp.hcci_diagnostics_enabled_by_vol[np.asarray(bundle.cylinder_indices, dtype=int)] == 1)
    fitted_c1_s = (1.47044752e-5, 2.13486288e-5)
    for cyl_idx, expected_c1_s in zip(bundle.cylinder_indices, fitted_c1_s, strict=True):
        cyl = int(cyl_idx)
        assert np.isclose(fp.hcci_tau_A_by_vol_s[cyl], expected_c1_s)
        assert fp.hcci_start_temperature_min_by_vol_K[cyl] == 780.0
        assert fp.hcci_start_pressure_min_by_vol_Pa[cyl] == 2.0e6
        assert fp.hcci_max_ignition_delay_by_vol_s[cyl] == 0.1
        assert fp.hcci_accumulation_end_mode_by_vol[cyl] == 0
    assert not free_piston_uses_hcci_diesel(bundle)
