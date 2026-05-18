from __future__ import annotations

import numpy as np

from thermo0d.output.reconstruction import SignalReconstructionService


def test_burn_window_energy_columns_are_built_per_pulse() -> None:
    t = np.array([0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6], dtype=float)
    columns = {
        'cylinder_added_energy_W': np.array([0.0, 10.0, 20.0, 0.0, 5.0, 5.0, 0.0], dtype=float),
    }

    SignalReconstructionService._add_burn_window_energy_columns(columns, t, ['cylinder'])

    np.testing.assert_array_equal(columns['cylinder_combustion_active_0to1'], np.array([0.0, 1.0, 1.0, 0.0, 1.0, 1.0, 0.0]))
    np.testing.assert_array_equal(columns['cylinder_burn_window_index'], np.array([0, 1, 1, 0, 2, 2, 0]))
    np.testing.assert_allclose(columns['cylinder_released_energy_window_progress_J'], np.array([0.0, 0.0, 1.5, 0.0, 0.0, 0.5, 0.0]))
    np.testing.assert_allclose(columns['cylinder_released_energy_window_J'], np.array([0.0, 1.5, 1.5, 0.0, 0.5, 0.5, 0.0]))
