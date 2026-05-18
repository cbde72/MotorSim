from __future__ import annotations

import numpy as np

from thermo0d.config.constants import AngleReference, CombCol
from thermo0d.model.free_piston.geometry import (
    cylinder_stroke_fraction_from_tdc,
    free_piston_is_compression_stroke,
    free_piston_local_cycle_angle_deg,
    free_piston_reference_is_active,
)
from thermo0d.physics.combustion import vibe_heat_release_rate


def test_free_piston_stroke_fraction_and_direction_detection() -> None:
    assert np.isclose(cylinder_stroke_fraction_from_tdc(0.00, 0.00, 0.08), 0.0)
    assert np.isclose(cylinder_stroke_fraction_from_tdc(0.04, 0.00, 0.08), 0.5)
    assert np.isclose(cylinder_stroke_fraction_from_tdc(0.08, 0.00, 0.08), 1.0)

    assert free_piston_is_compression_stroke(-0.1, 0.04, 0.00, 0.08) is True
    assert free_piston_is_compression_stroke(+0.1, 0.04, 0.00, 0.08) is False
    assert free_piston_is_compression_stroke(0.0, 0.00, 0.00, 0.08) is True
    assert free_piston_is_compression_stroke(0.0, 0.08, 0.00, 0.08) is False


def test_free_piston_local_cycle_angle_is_stroke_based() -> None:
    assert np.isclose(free_piston_local_cycle_angle_deg(0.00, +1.0, 0.00, 0.08, 360.0), 0.0)
    assert np.isclose(free_piston_local_cycle_angle_deg(0.04, +1.0, 0.00, 0.08, 360.0), 90.0)
    assert np.isclose(free_piston_local_cycle_angle_deg(0.08, +1.0, 0.00, 0.08, 360.0), 180.0)

    assert np.isclose(free_piston_local_cycle_angle_deg(0.08, -1.0, 0.00, 0.08, 360.0), 180.0)
    assert np.isclose(free_piston_local_cycle_angle_deg(0.04, -1.0, 0.00, 0.08, 360.0), 270.0)
    assert np.isclose(free_piston_local_cycle_angle_deg(0.00, -1.0, 0.00, 0.08, 360.0), 360.0)


def test_vibe_with_compression_tdc_reference_wraps_without_hard_expansion_cutoff() -> None:
    comb = np.zeros(len(CombCol), dtype=float)
    comb[CombCol.MODEL] = 1.0
    comb[CombCol.START_DEG] = 344.0
    comb[CombCol.DURATION_DEG] = 28.0
    comb[CombCol.A] = 6.9
    comb[CombCol.M] = 2.0
    comb[CombCol.FUEL_MASS_PER_CYCLE] = 420.0
    comb[CombCol.LHV] = 1.0
    comb[CombCol.REF_TYPE] = float(AngleReference.COMPRESSION_TDC)

    theta_local_compression = free_piston_local_cycle_angle_deg(0.002, -1.0, 0.00, 0.08, 360.0)
    theta_local_expansion = free_piston_local_cycle_angle_deg(0.002, +1.0, 0.00, 0.08, 360.0)

    qdot_compression = vibe_heat_release_rate.py_func(theta_local_compression, 0.0, 1000.0, comb, 360.0)

    assert theta_local_compression > 344.0
    assert theta_local_expansion < 20.0
    assert qdot_compression > 0.0
    assert free_piston_reference_is_active(int(comb[CombCol.REF_TYPE]), 0.002, -1.0, 0.00, 0.08) is True
    assert free_piston_reference_is_active(int(comb[CombCol.REF_TYPE]), 0.002, +1.0, 0.00, 0.08) is True
