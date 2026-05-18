from __future__ import annotations

import numpy as np

from thermo0d.compute.executor import TimeGridBuilder
from thermo0d.model.free_piston.simulator import build_time_grid
from thermo0d.output.sampling import OutputSampler


def test_time_grid_builder_reaches_exact_configured_end_time():
    grid = TimeGridBuilder.build(0.03, 0.10)
    assert np.allclose(grid, np.array([0.0, 0.03, 0.06, 0.09, 0.10]))


def test_free_piston_time_grid_reaches_exact_configured_end_time():
    grid = build_time_grid(0.03, 0.10)
    assert np.allclose(grid, np.array([0.0, 0.03, 0.06, 0.09, 0.10]))


def test_time_mode_sampling_keeps_exact_step_without_forcing_off_grid_endpoint():
    t = TimeGridBuilder.build(0.03, 0.23)
    sample_t = OutputSampler.build_sample_times_time(t, 0.05)
    assert np.allclose(sample_t, np.array([0.0, 0.05, 0.10, 0.15, 0.20]))
    assert np.allclose(np.diff(sample_t), np.full(sample_t.size - 1, 0.05))
