from __future__ import annotations

from thermo0d.config.models import RootConfig
from thermo0d.model.free_piston.forces import compute_load_force


def _base_cfg(load_model: str, damping: float = 0.0) -> dict:
    return {
        "modeling": {"architecture": "free_piston"},
        "preprocessing": {
            "gas_properties": {"cp_J_per_kgK": 1005.0, "cv_J_per_kgK": 718.0, "R_J_per_kgK": 287.0},
            "features": {"mass_flow": False, "wall_heat": False, "combustion": False, "evaporation": False, "pv_work": False},
            "engine": {"cycle_type": "2t", "speed_rpm": 1500.0},
            "volumes": [],
            "connections": [],
        },
        "simulation": {"dt_s": 1.0e-5, "total_cycles": 1, "save_last_cycles": 1, "simulationtime": 0.04, "solver": {"kind": "rk4", "rtol": 1.0e-6, "atol": 1.0e-9}},
        "postprocessing": {
            "csv_enabled": False, "excel_enabled": False,
            "sampling": {"mode": "time", "step_s": 1.0e-4},
            "final_cycle_uniform_angle_export": {"enabled": False, "step_deg": 1.0},
            "check_report": {"enabled": False, "html_enabled": False},
            "plots": {"enabled": False},
            "console": {"run_summary": {"enabled": False}, "cycle_summary": {"enabled": False}, "check_report": {"enabled": False}, "geometry": {"enabled": False}},
        },
        "free_piston": {
            "initial_conditions": {
                "x0_m": -0.039, "v0_m_per_s": 0.0,
                "cylinder": {"pressure_Pa": 101325.0, "temperature_K": 300.0},
                "bounce": {"pressure_Pa": 180000.0, "temperature_K": 300.0},
                "combustion_state": {"burned_fraction_0to1": 0.0, "released_energy_J": 0.0, "ignition_armed": False, "injection_armed": False},
            },
            "mechanics": {"moving_mass_kg": 1.0, "piston_area_m2": 0.00436, "clearance_volume_m3": 2.5e-5, "x_min_m": -0.04, "x_max_m": 0.04},
            "friction": {"model": "coulomb_viscous", "fc_N": 0.0, "cv_Ns_per_m": 0.0},
            "load": {"model": load_model, "damping_Ns_per_m": damping, "max_damping_Ns_per_m": 25.0 if load_model == "generator_controlled" else None, "control_zone_m": 0.01 if load_model == "generator_controlled" else None},
            "bounce": {"model": "gas_spring", "chamber_volume0_m3": 3.0e-4, "p0_Pa": 180000.0, "polytropic_exponent": 1.3},
        },
    }


def test_free_piston_load_model_none_is_allowed():
    cfg = RootConfig.model_validate(_base_cfg("none", 0.0))
    assert cfg.free_piston is not None
    assert cfg.free_piston.load.model == "none"


def test_free_piston_load_model_electromagnetic_linear_is_allowed():
    cfg = RootConfig.model_validate(_base_cfg("electromagnetic_linear", 12.0))
    assert cfg.free_piston is not None
    assert cfg.free_piston.load.model == "electromagnetic_linear"


def test_compute_load_force_supports_all_current_models():
    assert compute_load_force("none", 99.0, 2.0) == 0.0
    assert compute_load_force("viscous", 10.0, 2.0) == 20.0
    assert compute_load_force("electromagnetic_linear", 10.0, 2.0) == 20.0



def test_free_piston_load_model_generator_controlled_is_allowed():
    cfg = RootConfig.model_validate(_base_cfg("generator_controlled", 12.0))
    assert cfg.free_piston is not None
    assert cfg.free_piston.load.model == "generator_controlled"


def test_compute_load_force_supports_generator_controlled_model():
    near_left = compute_load_force(
        "generator_controlled",
        10.0,
        -2.0,
        x_m=-0.039,
        x_min_m=-0.04,
        x_max_m=0.04,
        max_damping_Ns_per_m=40.0,
        control_zone_m=0.01,
    )
    mid = compute_load_force(
        "generator_controlled",
        10.0,
        -2.0,
        x_m=0.0,
        x_min_m=-0.04,
        x_max_m=0.04,
        max_damping_Ns_per_m=40.0,
        control_zone_m=0.01,
    )
    assert abs(near_left) > abs(mid)


def test_generator_controlled_can_assist_when_velocity_is_low():
    assist_forward = compute_load_force(
        "generator_controlled",
        0.0,
        0.5,
        x_m=0.0,
        x_min_m=-0.04,
        x_max_m=0.04,
        max_damping_Ns_per_m=40.0,
        control_zone_m=0.01,
        assist_velocity_threshold_m_per_s=1.0,
        assist_force_N=20.0,
    )
    assist_backward = compute_load_force(
        "generator_controlled",
        0.0,
        -0.5,
        x_m=0.0,
        x_min_m=-0.04,
        x_max_m=0.04,
        max_damping_Ns_per_m=40.0,
        control_zone_m=0.01,
        assist_velocity_threshold_m_per_s=1.0,
        assist_force_N=20.0,
    )
    assert assist_forward < 0.0
    assert assist_backward > 0.0


def test_free_piston_load_model_generator_assist_fields_are_allowed():
    cfg_dict = _base_cfg("generator_controlled", 0.0)
    cfg_dict["free_piston"]["load"]["assist_velocity_threshold_m_per_s"] = 1.5
    cfg_dict["free_piston"]["load"]["assist_force_N"] = 350.0

    cfg = RootConfig.model_validate(cfg_dict)

    assert cfg.free_piston is not None
    assert cfg.free_piston.load.assist_velocity_threshold_m_per_s == 1.5
    assert cfg.free_piston.load.assist_force_N == 350.0
