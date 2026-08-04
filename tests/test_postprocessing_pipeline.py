from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np

from thermo0d.core.model_bundle import PostprocessingOptions
from thermo0d.output.pipeline import LastUtOtUtPipelineConfig, PipelineConfig, PipelinePostprocessingService, run_pipeline_from_raw_archive


class _Layout:
    def state_labels(self, volume_names=None):
        return ["state_1_m", "state_2_kg"]


def test_last_ut_ot_ut_rotary_axis_uses_mechanical_angle_and_relative_time(monkeypatch, tmp_path):
    bundle = SimpleNamespace(
        architecture="free_piston",
        postprocessing=PostprocessingOptions(mode="pipeline", pipeline_config=None, outdir=None),
        free_piston=SimpleNamespace(
            x_state_index=0,
            v_state_index=1,
            kinematics_type="oscillating_rotary",
        ),
    )
    service = PipelinePostprocessingService(bundle, tmp_path / "config.yaml")
    cfg = PipelineConfig(last_ut_ot_ut=LastUtOtUtPipelineConfig(
        enabled=True,
        step_deg=90.0,
        axis_min_deg=-9.0,
        axis_max_deg=9.0,
        axis_signal="theta_deg",
    ))
    t = np.arange(5, dtype=np.float64)
    q_rad = np.deg2rad(np.array([-9.0, 0.0, 9.0, 0.0, -9.0]))
    q_dot = np.array([0.0, 1.0, 0.0, -1.0, 0.0])
    y = np.vstack([q_rad, q_dot])
    columns = {
        "t_s": t,
        "theta_deg": np.zeros(5),
        "value": np.arange(5, dtype=np.float64),
    }
    turning_point = lambda idx: SimpleNamespace(sample_index=idx)
    monkeypatch.setattr(
        "thermo0d.output.pipeline.find_last_ut_ot_ut_turning_points",
        lambda *_args, **_kwargs: (turning_point(0), turning_point(2), turning_point(4)),
    )

    sampled = service._sample_last_ut_ot_ut_columns(
        cfg,
        keys=["t_s", "theta_deg", "value"],
        columns=columns,
        t=t,
        y=y,
    )

    assert sampled is not None
    np.testing.assert_allclose(sampled["theta_deg"], [-9.0, 0.0, 9.0, 0.0, -9.0])
    np.testing.assert_allclose(sampled["last_cycle_time_s"], [0.0, 1.0, 2.0, 3.0, 4.0])


def test_plot_layout_signal_keys_include_event_trigger_signals(tmp_path):
    layout = tmp_path / "events.yaml"
    layout.write_text(
        """
figures:
- subplots:
  - x_signal: theta_deg
    series:
    - signal_key: cylinder_1_hcci_ignition_delay_s
      show_while_positive_signal: cylinder_1_hcci_accumulation_window_active_0to1
    text_box:
      metrics:
      - signal_key: last_cycle_time_s
        where_signal: exhaust_slot_1_A_geom_m2
      - signal_key: theta_deg
        where_signal_any:
        - cylinder_1_combustion_active_0to1
        - cylinder_1_added_energy_W
""".strip(),
        encoding="utf-8",
    )

    keys = PipelinePostprocessingService._plot_layout_signal_keys(layout)

    assert {
        "theta_deg",
        "last_cycle_time_s",
        "cylinder_1_hcci_ignition_delay_s",
        "cylinder_1_hcci_accumulation_window_active_0to1",
        "exhaust_slot_1_A_geom_m2",
        "cylinder_1_combustion_active_0to1",
        "cylinder_1_added_energy_W",
    } <= keys


def test_pipeline_writes_raw_and_filters_zero_columns(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("postprocessing:\n  mode: pipeline\n", encoding="utf-8")
    post_cfg = tmp_path / "postprocessing.yaml"
    post_cfg.write_text(
        """
version: 1
raw:
  enabled: true
  path: raw/run_raw.npz
  compression: none
  dtype: float64
signals:
  selected:
    - t_s
    - state_1_m
    - state_2_kg
  include_kinds: [raw]
  remove_zero_columns: true
csv:
  enabled: true
  path: csv/signals.csv
  separator: ";"
  include_units_row: true
  include_kind_row: true
reconstruction:
  enabled: false
integrals:
  enabled: false
summary:
  enabled: true
  path: summary/run_summary.yaml
  text_path: summary/run_summary.txt
""".strip(),
        encoding="utf-8",
    )
    bundle = SimpleNamespace(
        architecture="classic",
        postprocessing=PostprocessingOptions(mode="pipeline", pipeline_config=str(post_cfg), outdir=None),
        state_layout=_Layout(),
        volume_names=[],
        y_init=np.zeros(2),
    )
    t = np.array([0.0, 0.1, 0.2], dtype=np.float64)
    y = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 2.0, 3.0],
        ],
        dtype=np.float64,
    )
    cycles = np.zeros(3, dtype=np.int64)

    artifacts = PipelinePostprocessingService(bundle, config_path).run(t, y, cycles)

    assert artifacts.raw_archive_path is not None
    assert artifacts.csv_path is not None
    assert artifacts.summary_path is not None
    csv_text = Path(artifacts.csv_path).read_text(encoding="utf-8")
    assert "state_1_m" not in csv_text
    assert "state_2_kg" in csv_text
    with np.load(artifacts.raw_archive_path) as raw:
        assert raw["y"].shape == (2, 3)
    summary_text = Path(artifacts.summary_path).read_text(encoding="utf-8")
    assert "cycles_detected" in summary_text


def test_offline_pipeline_reprocesses_raw_archive(tmp_path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("postprocessing:\n  mode: pipeline\n", encoding="utf-8")
    post_cfg = tmp_path / "postprocessing.yaml"
    post_cfg.write_text(
        """
version: 1
raw:
  enabled: true
  path: raw/run_raw.npz
signals:
  selected: [t_s, state_2_kg]
  include_kinds: [raw]
  remove_zero_columns: true
csv:
  enabled: true
  path: csv/signals.csv
summary:
  enabled: true
  path: summary/run_summary.yaml
  text_path: summary/run_summary.txt
reconstruction:
  enabled: false
integrals:
  enabled: false
offline:
  enabled: true
""".strip(),
        encoding="utf-8",
    )
    bundle = SimpleNamespace(
        architecture="classic",
        postprocessing=PostprocessingOptions(mode="pipeline", pipeline_config=str(post_cfg), outdir=None),
        state_layout=_Layout(),
        volume_names=[],
        y_init=np.zeros(2),
    )
    t = np.array([0.0, 0.1, 0.2], dtype=np.float64)
    y = np.array([[0.0, 0.0, 0.0], [1.0, 2.0, 3.0]], dtype=np.float64)
    cycles = np.zeros(3, dtype=np.int64)
    online = PipelinePostprocessingService(bundle, config_path).run(t, y, cycles)

    outdir = tmp_path / "offline"
    offline = run_pipeline_from_raw_archive(online.raw_archive_path, post_cfg, output_dir=outdir)

    assert offline.csv_path is not None
    assert offline.summary_path is not None
    assert "state_2_kg" in Path(offline.csv_path).read_text(encoding="utf-8")
