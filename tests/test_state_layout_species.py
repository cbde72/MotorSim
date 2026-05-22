from __future__ import annotations

import numpy as np

from thermo0d.core.state_layout import StateLayout


def test_residual_and_fresh_burned_are_separate_species_buckets() -> None:
    layout = StateLayout.classic(1)
    y = np.zeros(layout.total_size, dtype=np.float64)
    y[layout.mass_index(0)] = 1.0
    y[layout.burned_mass_index(0)] = 0.30
    y[layout.residual_mass_index(0)] = 0.10

    assert layout.residual_mass_from_state(y, 0) == 0.10
    assert layout.fresh_burned_mass_from_state(y, 0) == 0.20


def test_residual_mass_is_clamped_to_burned_mass() -> None:
    layout = StateLayout.classic(1)
    y = np.zeros(layout.total_size, dtype=np.float64)
    y[layout.mass_index(0)] = 1.0
    y[layout.burned_mass_index(0)] = 0.30
    y[layout.residual_mass_index(0)] = 0.50

    assert layout.residual_mass_from_state(y, 0) == 0.30
    assert layout.fresh_burned_mass_from_state(y, 0) == 0.0
