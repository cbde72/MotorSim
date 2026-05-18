from __future__ import annotations

import numpy as np

from thermo0d.compute.analysis import CycleIndexCalculator
from thermo0d.output.rows import ResultRowBuilder
from thermo0d.output.sampling import OutputSampler


class _DummyBundle:
    def __init__(self):
        self.gas_props = (1000.0, 718.0, 287.0, 1.4)
        self.vol_matrix = np.zeros((0, 8), dtype=np.float64)
        self.conn_matrix = np.zeros((0, 8), dtype=np.float64)
        self.feature_flags = np.zeros(8, dtype=np.float64)
        self.volume_names = []
        self.connection_names = []
        self.cylinder_indices = []


def test_cycle_index_keeps_exact_end_in_last_cycle() -> None:
    t = np.array([0.0, 0.5, 1.0, 1.5, 2.0], dtype=np.float64)
    idx = CycleIndexCalculator.compute(t, 1.0, total_cycles=2)
    assert idx.tolist() == [0, 0, 0, 1, 1]


def test_output_sampler_keeps_exact_end_in_last_cycle() -> None:
    sample_t = np.array([1.0, 1.5, 2.0], dtype=np.float64)
    idx = OutputSampler.build_cycle_indices(sample_t, 1.0, total_cycles=2)
    assert idx.tolist() == [0, 1, 1]


def test_result_rows_place_theta_local_in_second_column() -> None:
    rows = ResultRowBuilder.build(_DummyBundle(), np.array([0.0]), np.zeros((0, 1), dtype=np.float64), np.array([0], dtype=int))
    assert list(rows[0].keys())[:4] == ['t_s', 'theta_local_deg', 'theta_deg', 'cycle_index']
