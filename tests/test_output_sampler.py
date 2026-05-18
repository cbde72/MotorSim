import numpy as np

from thermo0d.output.sampling import OutputSampler


def test_output_sampler_time_mode_builds_exact_sample_times():
    t = np.array([0.0, 0.01, 0.02, 0.03, 0.04], dtype=float)
    sample_t = OutputSampler.build_sample_times(t, cycle_period_s=0.04, cycle_deg=720.0, sampling_mode='time', sampling_step=0.015)
    assert np.allclose(sample_t, np.array([0.0, 0.015, 0.03], dtype=float))


def test_output_sampler_angle_mode_builds_exact_sample_times():
    t = np.array([0.0, 0.01, 0.02, 0.03, 0.04], dtype=float)
    sample_t = OutputSampler.build_sample_times(t, cycle_period_s=0.04, cycle_deg=360.0, sampling_mode='crank_angle', sampling_step=135.0)
    assert np.allclose(sample_t, np.array([0.0, 0.015, 0.03], dtype=float))


def test_output_sampler_interpolates_to_exact_times():
    t = np.array([0.0, 0.01, 0.02], dtype=float)
    y = np.array([[0.0, 10.0, 20.0], [100.0, 110.0, 120.0]], dtype=float)
    sample_t = np.array([0.0, 0.005, 0.015], dtype=float)
    sample_y = OutputSampler.interpolate_states(t, y, sample_t)
    assert np.allclose(sample_y[0], np.array([0.0, 5.0, 15.0], dtype=float))
    assert np.allclose(sample_y[1], np.array([100.0, 105.0, 115.0], dtype=float))
