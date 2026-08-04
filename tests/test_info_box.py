from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from thermo0d.output.info_box import build_info_box_text, draw_info_box, required_info_box_signal_keys


def _rows(cylinder: str) -> list[dict[str, float]]:
    return [
        {
            "t_s": 0.00,
            "theta_deg": 180.0,
            f"{cylinder}_p_Pa": 1.0e5,
            f"{cylinder}_V_m3": 2.0e-4,
            f"{cylinder}_added_energy_W": 0.0,
            f"{cylinder}_wall_heat_W": -100.0,
            f"{cylinder}_T_K": 500.0,
            f"{cylinder}_thermo_lambda": 1.8,
            f"{cylinder}_combustion_active_0to1": 0.0,
            f"{cylinder}_share_burned_0to1": 0.1,
        },
        {
            "t_s": 0.01,
            "theta_deg": 360.0,
            f"{cylinder}_p_Pa": 20.0e5,
            f"{cylinder}_V_m3": 1.0e-4,
            f"{cylinder}_added_energy_W": 1000.0,
            f"{cylinder}_wall_heat_W": -200.0,
            f"{cylinder}_T_K": 900.0,
            f"{cylinder}_thermo_lambda": 1.7,
            f"{cylinder}_combustion_active_0to1": 1.0,
            f"{cylinder}_share_burned_0to1": 0.2,
        },
        {
            "t_s": 0.02,
            "theta_deg": 540.0,
            f"{cylinder}_p_Pa": 1.2e5,
            f"{cylinder}_V_m3": 2.0e-4,
            f"{cylinder}_added_energy_W": 0.0,
            f"{cylinder}_wall_heat_W": -100.0,
            f"{cylinder}_T_K": 550.0,
            f"{cylinder}_thermo_lambda": 1.7,
            f"{cylinder}_combustion_active_0to1": 0.0,
            f"{cylinder}_share_burned_0to1": 0.3,
        },
    ]


def _subplot(cylinder: str) -> dict:
    return {"info_box": {"enabled": True, "kind": "last_ut_ot_ut_pv", "cylinder": cylinder}}


def test_pv_info_box_uses_requested_cylinder_2() -> None:
    text = build_info_box_text(_rows("cylinder_2"), _subplot("cylinder_2"), Path("plot.yaml"), Path("."))
    assert "pmax: 20.00 bar" in text
    assert "Wandwaermeverluste:" in text
    keys = required_info_box_signal_keys(_subplot("cylinder_2"))
    assert "cylinder_2_added_energy_W" in keys
    assert "cylinder_2_wall_heat_W" in keys


def test_shared_draw_function_adds_box_for_cylinder_1() -> None:
    fig, axis = plt.subplots()
    text = draw_info_box(axis, _subplot("cylinder_1"), _rows("cylinder_1"), Path("plot.yaml"), Path("."))
    assert text
    assert len(axis.texts) == 1
    assert "Zugef. Energie:" in axis.texts[0].get_text()
    plt.close(fig)
