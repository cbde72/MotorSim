from __future__ import annotations

import numpy as np
from pathlib import Path

from thermo0d.config.constants import ConnCol, ConnectionType, KinCol, VolumeCol, VolumeType
from thermo0d.core.model_bundle import ModelBundle, PostprocessingOptions, SimulationOptions
from thermo0d.output.console import ConsoleArtifactReporter, ConsoleGeometryReporter
from tests.test_runner import _prepare_case
from thermo0d.app.runner import run_simulation


def test_artifact_reporter_returns_expected_states(tmp_path: Path):
    existing = tmp_path / 'ok.csv'
    existing.write_text('x', encoding='utf-8')
    missing = tmp_path / 'missing.csv'

    assert ConsoleArtifactReporter._status_for_path(existing) == 'ok'
    assert ConsoleArtifactReporter._status_for_path(missing) == 'failed'
    assert ConsoleArtifactReporter._status_for_path(None) == 'warn'
    assert ConsoleArtifactReporter._status_for_many([existing]) == 'ok'
    assert ConsoleArtifactReporter._status_for_many([existing, missing]) == 'failed'
    assert ConsoleArtifactReporter._status_for_many([]) == 'warn'


def test_geometry_report_includes_cylinder_and_connection_units():
    vol_matrix = np.zeros((1, len(VolumeCol)), dtype=np.float64)
    vol_matrix[0, VolumeCol.TYPE] = float(VolumeType.CYLINDER)
    vol_matrix[0, VolumeCol.KIN_ROW] = 0.0

    kin_matrix = np.zeros((1, len(KinCol)), dtype=np.float64)
    kin_matrix[0, KinCol.BORE] = 0.086
    kin_matrix[0, KinCol.STROKE] = 0.086
    kin_matrix[0, KinCol.CONROD] = 0.143
    kin_matrix[0, KinCol.COMPRESSION_RATIO] = 10.5

    conn_matrix = np.full((1, len(ConnCol)), -1.0, dtype=np.float64)
    conn_matrix[0, ConnCol.TYPE] = float(ConnectionType.VALVE)
    conn_matrix[0, ConnCol.FROM_VOL] = 0.0
    conn_matrix[0, ConnCol.TO_VOL] = 0.0
    conn_matrix[0, ConnCol.LIFT_SCALE] = 1.0
    conn_matrix[0, ConnCol.LASH] = 0.0001
    conn_matrix[0, ConnCol.PROFILE_START] = 0.0
    conn_matrix[0, ConnCol.PROFILE_LEN] = 3.0
    conn_matrix[0, ConnCol.ALPHA_START] = 0.0
    conn_matrix[0, ConnCol.ALPHA_LEN] = 3.0
    conn_matrix[0, ConnCol.REF_FLOW_AREA] = 0.25 * np.pi * 0.086 * 0.086

    lift_table = np.array([
        [0.0, 0.0],
        [90.0, 0.0080],
        [180.0, 0.0],
    ], dtype=np.float64)
    alpha_table = np.array([
        [0.0, 0.0, 0.0],
        [0.0040, 0.15, 0.12],
        [0.0080, 0.28, 0.24],
    ], dtype=np.float64)

    bundle = ModelBundle(
        y_init=np.zeros((2,), dtype=np.float64),
        vol_matrix=vol_matrix,
        kin_matrix=kin_matrix,
        conn_matrix=conn_matrix,
        wall_matrix=np.zeros((0, 6), dtype=np.float64),
        comb_matrix=np.zeros((0, 8), dtype=np.float64),
        evap_matrix=np.zeros((0, 6), dtype=np.float64),
        lift_table=lift_table,
        alpha_table=alpha_table,
        cd_table=np.zeros((0, 3), dtype=np.float64),
        gas_props=np.zeros((4,), dtype=np.float64),
        feature_flags=np.zeros((5,), dtype=np.int64),
        cycle_period_s=0.04,
        cycle_deg=720.0,
        volume_names=['cylinder'],
        connection_names=['intake_valve'],
        cylinder_indices=[0],
        simulation=SimulationOptions(dt_s=1.0e-5, total_cycles=1, save_last_cycles=1, solver_kind='rk4', rtol=1.0e-6, atol=1.0e-9),
        postprocessing=PostprocessingOptions(csv_path='results/out.csv', csv_separator=';', sampling_mode='time', sampling_step=1.0e-4),
    )

    lines = ConsoleGeometryReporter.build_lines(bundle)

    assert any(line.startswith('[geometry:cylinder]') for line in lines)
    assert any('bore_mm=' in line and 'swept_cm3=' in line and 'clearance_cm3=' in line for line in lines)
    assert any('A_ref_mm2=' in line and 'A_eff_forward_max_mm2=' in line for line in lines if '[geometry:valve]' in line)
    assert all('mm=' in line or 'mm2=' in line or 'cm3=' in line for line in lines)


def test_run_simulation_console_export_statuses_are_simplified(capsys):
    work_dir, cfg = _prepare_case('runner_console_statuses', 'Projekte/config_1cyl_2t.yaml', 'config_console_status.yaml', 'run_console_status.csv')
    run_simulation(cfg, excel=False)
    out = capsys.readouterr().out
    assert '[csv] OK' in out
    assert '[plot] OK' in out
    assert '[plot.yaml] OK' in out
    assert '[plot10.yaml] OK' in out
    assert '[csv:check-report] OK' in out
    assert str(work_dir) not in out
    assert 'run_console_status.csv' not in out


def test_geometry_report_includes_slot_max_effective_areas():
    vol_matrix = np.zeros((1, len(VolumeCol)), dtype=np.float64)
    vol_matrix[0, VolumeCol.TYPE] = float(VolumeType.CYLINDER)
    vol_matrix[0, VolumeCol.KIN_ROW] = 0.0

    kin_matrix = np.zeros((1, len(KinCol)), dtype=np.float64)
    kin_matrix[0, KinCol.BORE] = 0.080
    kin_matrix[0, KinCol.STROKE] = 0.090
    kin_matrix[0, KinCol.CONROD] = 0.140
    kin_matrix[0, KinCol.COMPRESSION_RATIO] = 9.5

    conn_matrix = np.full((1, len(ConnCol)), -1.0, dtype=np.float64)
    conn_matrix[0, ConnCol.TYPE] = float(ConnectionType.SLOT)
    conn_matrix[0, ConnCol.FROM_VOL] = 0.0
    conn_matrix[0, ConnCol.TO_VOL] = 0.0
    conn_matrix[0, ConnCol.PRIMARY_DIM] = 0.020
    conn_matrix[0, ConnCol.SECONDARY_DIM] = 0.015
    conn_matrix[0, ConnCol.N_HOLES] = 2.0
    conn_matrix[0, ConnCol.CD_MODE] = 1.0
    conn_matrix[0, ConnCol.CD_FORWARD] = 0.8
    conn_matrix[0, ConnCol.CD_REVERSE] = 0.6

    bundle = ModelBundle(
        y_init=np.zeros((2,), dtype=np.float64),
        vol_matrix=vol_matrix,
        kin_matrix=kin_matrix,
        conn_matrix=conn_matrix,
        wall_matrix=np.zeros((0, 6), dtype=np.float64),
        comb_matrix=np.zeros((0, 8), dtype=np.float64),
        evap_matrix=np.zeros((0, 6), dtype=np.float64),
        lift_table=np.zeros((0, 2), dtype=np.float64),
        alpha_table=np.zeros((0, 3), dtype=np.float64),
        cd_table=np.zeros((0, 3), dtype=np.float64),
        gas_props=np.zeros((4,), dtype=np.float64),
        feature_flags=np.zeros((5,), dtype=np.int64),
        cycle_period_s=0.04,
        cycle_deg=360.0,
        volume_names=['cylinder'],
        connection_names=['transfer_slot'],
        cylinder_indices=[0],
        simulation=SimulationOptions(dt_s=1.0e-5, total_cycles=1, save_last_cycles=1, solver_kind='rk4', rtol=1.0e-6, atol=1.0e-9),
        postprocessing=PostprocessingOptions(csv_path='results/out.csv', csv_separator=';', sampling_mode='time', sampling_step=1.0e-4),
    )

    lines = ConsoleGeometryReporter.build_lines(bundle)
    slot_lines = [line for line in lines if '[geometry:slot]' in line]
    assert slot_lines
    assert 'A_eff_forward_max_mm2=' in slot_lines[0]
    assert 'A_eff_reverse_max_mm2=' in slot_lines[0]
