from pathlib import Path

import numpy as np

from thermo0d.config.constants import VolumeCol
from thermo0d.config.models import load_config
from thermo0d.input.model_builder import build_model_bundle
from thermo0d.model.free_piston.forces import compute_load_force


def test_generator_controlled_load_increases_near_limit() -> None:
    far_force = compute_load_force(
        "generator_controlled", 10.0, 2.0, x_m=0.04, x_min_m=0.0, x_max_m=0.08, moving_mass_kg=0.7, control_zone_m=0.01, target_margin_m=0.001, min_stop_distance_m=0.0005, max_force_N=5000.0, k_stop=1.0,
    )
    near_force = compute_load_force(
        "generator_controlled", 10.0, 2.0, x_m=0.079, x_min_m=0.0, x_max_m=0.08, moving_mass_kg=0.7, control_zone_m=0.01, target_margin_m=0.001, min_stop_distance_m=0.0005, max_force_N=5000.0, k_stop=1.0,
    )
    assert abs(near_force) > abs(far_force)


def test_free_piston_vibe_generator_config_builds_comb_matrix() -> None:
    cfg_path = Path('Projekte/variants/free_piston_vibe_generator_controlled.yaml')
    cfg = load_config(cfg_path)
    bundle = build_model_bundle(cfg, cfg_path)
    assert bundle.comb_matrix.shape[0] == 1
    comb_row = bundle.comb_matrix[0]
    assert comb_row[5] > 0.0
    assert int(bundle.vol_matrix[bundle.cylinder_indices[0], VolumeCol.COMB_ROW]) == 0
