from __future__ import annotations

import numpy as np
import pytest

from thermo0d.output.sampling import OutputSampler


def test_grid_targets_validates_inputs():
    with pytest.raises(ValueError):
        OutputSampler._grid_targets(0.0, 1.0, 0.0)
    with pytest.raises(ValueError):
        OutputSampler._grid_targets(2.0, 1.0, 0.1)


def test_build_sample_times_empty_input():
    t = np.zeros(0, dtype=float)
    assert OutputSampler.build_sample_times_time(t, 0.1).size == 0
    assert OutputSampler.build_sample_times_angle(t, 0.1, 360.0, 1.0).size == 0


def test_build_sample_times_invalid_mode():
    with pytest.raises(ValueError):
        OutputSampler.build_sample_times(np.array([0.0, 1.0]), 1.0, 360.0, 'bad', 0.1)


def test_interpolate_states_validation_errors():
    t = np.array([0.0, 1.0])
    y = np.array([0.0, 1.0])
    with pytest.raises(ValueError):
        OutputSampler.interpolate_states(t, y, np.array([0.5]))
    with pytest.raises(ValueError):
        OutputSampler.interpolate_states(np.array([[0.0, 1.0]]), np.zeros((1, 2)), np.array([0.5]))
    with pytest.raises(ValueError):
        OutputSampler.interpolate_states(np.array([0.0, 1.0, 2.0]), np.zeros((1, 2)), np.array([0.5]))


def test_build_cycle_indices_clamps():
    sample_t = np.array([-1.0, 0.0, 0.99, 2.01, 9.99])
    idx = OutputSampler.build_cycle_indices(sample_t, 1.0, 3)
    assert idx.tolist() == [0, 0, 0, 2, 2]


def test_build_keep_mask_invalid_mode():
    with pytest.raises(ValueError):
        OutputSampler.build_keep_mask(np.array([0.0, 1.0]), 1.0, 360.0, 'bad', 0.1)
