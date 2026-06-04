from pathlib import Path

import numpy as np

from thermo0d.input.config_loader import ConfigLoader
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.model.free_piston.combustion_latch import free_piston_uses_hcci_diesel
from thermo0d.output.reconstruction import SignalReconstructionService


def test_vibe_hcci_diagnostics_do_not_enable_autoignition_rhs() -> None:
    config_path = Path("Projekte/variants/free_piston_GenSet_V25.yaml")
    cfg = ConfigLoader.load(config_path)
    bundle = build_model_bundle(cfg, config_path)
    fp = bundle.free_piston

    assert fp is not None
    assert not np.any(fp.hcci_enabled_by_vol)
    assert np.any(fp.hcci_diagnostics_enabled_by_vol)
    assert not free_piston_uses_hcci_diesel(bundle)


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
