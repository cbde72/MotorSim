from __future__ import annotations

from pathlib import Path

from thermo0d.config.constants import VolumeCol
from thermo0d.config.models import load_config
from thermo0d.input.model_builder import MatrixModelBuilder


def test_builder_accepts_disabled_combustion_and_evaporation_models(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
preprocessing:
  gas_properties:
    cp_J_per_kgK: 1005.0
    cv_J_per_kgK: 718.0
    R_J_per_kgK: 287.0
  features:
    mass_flow: true
    wall_heat: false
    combustion: false
    evaporation: false
    pv_work: true
  engine:
    cycle_type: 4t
    speed_rpm: 3000.0
  volumes:
    - name: cyl1
      type: cylinder
      initial_pressure_Pa: 101325.0
      initial_temperature_K: 300.0
      kinematics:
        type: crank_slider
        bore_m: 0.086
        stroke_m: 0.086
        conrod_m: 0.143
        compression_ratio: 10.0
        phase_deg: 0.0
      wall_heat:
        model: none
      combustion:
        model: none
        angle_reference: absolute
      evaporation:
        model: none
        angle_reference: absolute
  connections: []
simulation:
  dt_s: 1.0e-6
  total_cycles: 1
  save_last_cycles: 1
  solver:
    kind: rk4
    rtol: 1.0e-6
    atol: 1.0e-9
postprocessing:
  csv_path: out.csv
  csv_separator: ","
  sampling:
    mode: crank_angle
    step_deg: 1.0
""".strip(),
        encoding="utf-8",
    )

    root = load_config(config_path)
    bundle = MatrixModelBuilder(root, config_path).build()

    assert bundle.vol_matrix.shape[0] == 1
    assert bundle.vol_matrix[0, VolumeCol.COMB_ROW] == -1.0
    assert bundle.vol_matrix[0, VolumeCol.EVAP_ROW] == -1.0
