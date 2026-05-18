from __future__ import annotations

from pathlib import Path

import numpy as np

from thermo0d.app.runner import run_simulation
from tests.test_runner import _prepare_case


def test_uniform_last_cycle_export_writes_full_angle_grid() -> None:
    _, cfg = _prepare_case(
        'runner_uniform_last_cycle',
        'Projekte/config_1cyl_2t.yaml',
        'config_uniform_last_cycle.yaml',
        'run_uniform_last_cycle.csv',
        [
            (
                'csv_separator: ","\n  sampling:',
                'csv_separator: ","\n  final_cycle_uniform_angle_export:\n    enabled: true\n    step_deg: 30.0\n  sampling:',
            ),
        ],
    )
    artifacts = run_simulation(cfg, excel=False)
    assert artifacts.last_cycle_uniform_csv_path is not None
    uniform_csv = Path(artifacts.last_cycle_uniform_csv_path)
    assert uniform_csv.exists()

    lines = uniform_csv.read_text(encoding='utf-8').splitlines()
    header = lines[0].split(',')
    theta_idx = header.index('theta_local_deg')
    cycle_idx = header.index('cycle_index')
    rows = [line.split(',') for line in lines[1:] if line.strip()]
    thetas = np.array([float(r[theta_idx]) for r in rows], dtype=float)
    cycles = {int(float(r[cycle_idx])) for r in rows}
    assert cycles == {artifacts.bundle.simulation.total_cycles - 1}
    assert np.allclose(np.diff(thetas), 30.0, atol=1.0e-9, rtol=0.0)
    assert abs(thetas[0] - 0.0) <= 1.0e-9
    assert abs(thetas[-1] - artifacts.bundle.cycle_deg) <= 1.0e-9
