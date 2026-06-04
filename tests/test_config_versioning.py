from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / 'src'
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from thermo0d.config_versioning import migrate_config_data, migrate_yaml_text
from thermo0d.version import CURRENT_CONFIG_SCHEMA_VERSION


def test_migrate_config_data_renames_and_defaults() -> None:
    raw = {
        "preprocessing": {
            "features": {"mass_flow": True, "heat_transfer": True},
            "volumes": [
                {
                    "name": "cylinder",
                    "type": "cylinder",
                    "initial_mass_kg": 1.0,
                    "initial_temperature_K": 300.0,
                    "kinematics": {"type": "crank_slider", "bore_m": 0.08, "stroke_m": 0.08, "conrod_m": 0.13, "compression_ratio": 10.0, "phase_deg": 0.0},
                    "wall_heat": {"model": "none"},
                    "combustion": {"model": "vibe", "start_deg": 0.0, "duration_deg": 1.0, "a": 1.0, "m": 1.0, "fuel_mass_per_cycle_kg": 1.0, "lhv_J_per_kg": 1.0, "angle_ref": "absolute"},
                    "evaporation": {"model": "none"},
                }
            ],
            "connections": [
                {
                    "name": "intake_valve",
                    "type": "valve",
                    "from_volume": "plenum",
                    "to_volume": "cylinder",
                    "opening_angle_deg": 10.0,
                    "opening_ref": "absolute",
                    "profile_angle_domain": "crank",
                    "lift_scale": 1.0,
                    "lash_m": 0.0,
                    "lift_file": "lift.csv",
                    "alphak_file": "alpha.csv",
                }
            ],
        },
        "simulation": {"dt_s": 1.0e-5, "total_cycles": 1, "save_last_cycles": 1, "solver": {"method": "rk4", "rtol": 1.0e-6, "atol": 1.0e-9}},
        "postprocessing": {"csv_path": "out.csv", "csv_sep": ";", "sampling": {"mode": "angle", "step_ca_deg": 1.0}},
    }

    migrated = migrate_config_data(raw)

    assert migrated["versioning"]["config_schema_version"] == CURRENT_CONFIG_SCHEMA_VERSION
    assert migrated["preprocessing"]["features"]["wall_heat"] is True
    assert "heat_transfer" not in migrated["preprocessing"]["features"]
    assert migrated["simulation"]["solver"]["kind"] == "rk4"
    assert migrated["postprocessing"]["csv_separator"] == ";"
    assert migrated["postprocessing"]["mode"] == "pipeline"
    assert migrated["postprocessing"]["sampling"]["mode"] == "crank_angle"
    assert migrated["postprocessing"]["sampling"]["step_deg"] == 1.0
    assert migrated["preprocessing"]["volumes"][0]["combustion"]["angle_reference"] == "absolute"
    assert migrated["preprocessing"]["connections"][0]["opening_reference"] == "absolute"
    assert migrated["preprocessing"]["connections"][0]["alpha_k_file"] == "alpha.csv"
    assert "final_cycle_uniform_angle_export" in migrated["postprocessing"]


def test_migrate_yaml_text_preserves_comments_and_updates_keys() -> None:
    original = """# Kopfkommentar
preprocessing:
  features:
    # alter Name
    heat_transfer: true
simulation:
  solver:
    method: rk4
postprocessing:
  mode: legacy
  csv_path: results/out.csv
  csv_sep: ";"
  sampling:
    mode: angle
    step_ca_deg: 1.0
"""
    upgraded = migrate_config_data(
        {
            "preprocessing": {"features": {"heat_transfer": True}},
            "simulation": {"solver": {"method": "rk4"}},
            "postprocessing": {"csv_path": "results/out.csv", "csv_sep": ";", "sampling": {"mode": "angle", "step_ca_deg": 1.0}},
        }
    )

    text = migrate_yaml_text(original, upgraded)

    assert "# Kopfkommentar" in text
    assert "# alter Name" in text
    assert "wall_heat: true" in text
    assert "kind: rk4" in text
    assert 'csv_separator: ";"' in text
    assert "mode: pipeline" in text
    assert "mode: legacy" not in text
    assert "mode: crank_angle" in text
    assert "step_deg: 1.0" in text
    assert "final_cycle_uniform_angle_export:" in text
    assert "versioning:" in text


def test_auto_update_false_does_not_overwrite_free_piston_cylinder_initials() -> None:
    raw = {
        "modeling": {"architecture": "free_piston"},
        "preprocessing": {
            "gas_properties": {"cp_J_per_kgK": 1005.0, "cv_J_per_kgK": 718.0, "R_J_per_kgK": 287.0},
            "features": {"mass_flow": False, "wall_heat": False, "combustion": False, "evaporation": False, "pv_work": True},
            "engine": {"cycle_type": "2t", "speed_rpm": 25.0},
            "volumes": [
                {
                    "name": "cylinder",
                    "type": "cylinder",
                    "initial_pressure_Pa": 120000.0,
                    "initial_temperature_K": 320.0,
                    "kinematics": {"type": "crank_slider", "bore_m": 0.0745, "stroke_m": 0.08, "conrod_m": 0.12, "compression_ratio": 10.0, "phase_deg": 0.0},
                    "wall_heat": {"model": "none"},
                    "combustion": {"model": "none"},
                    "evaporation": {"model": "none"},
                }
            ],
            "connections": [],
        },
        "simulation": {"dt_s": 1.0e-5, "total_cycles": 1, "save_last_cycles": 1, "solver": {"kind": "rk4", "rtol": 1.0e-6, "atol": 1.0e-9}},
        "postprocessing": {"auto_update_initial_conditions": False},
        "free_piston": {
            "initial_conditions": {
                "x0_m": 0.01,
                "v0_m_per_s": 0.0,
                "cylinder": {"pressure_Pa": 999000.0, "temperature_K": 999.0},
                "bounce": {"pressure_Pa": 180000.0, "temperature_K": 300.0},
            },
            "mechanics": {"moving_mass_kg": 2.0, "piston_area_m2": 0.00436, "clearance_volume_m3": 2.5e-5, "x_min_m": 0.0, "x_max_m": 0.08},
            "friction": {"model": "coulomb_viscous", "fc_N": 0.0, "cv_Ns_per_m": 0.0},
            "load": {"model": "none", "damping_Ns_per_m": 0.0},
            "bounce": {"model": "gas_spring", "chamber_volume0_m3": 5.0e-4, "p0_Pa": 180000.0, "polytropic_exponent": 1.3},
        },
    }

    migrated = migrate_config_data(raw)

    cylinder = migrated["preprocessing"]["volumes"][0]
    assert cylinder["initial_pressure_Pa"] == 120000.0
    assert cylinder["initial_temperature_K"] == 320.0
    assert "cylinder" not in migrated["free_piston"]["initial_conditions"]
