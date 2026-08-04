from types import SimpleNamespace

import pytest

from thermo0d.config.restart_state_update import RestartStateSample, _update_free_piston_initial_conditions
from thermo0d.model.free_piston.builder import _initial_cylinder_burned_fraction_0to1


def test_named_cylinder_composition_overrides_global_legacy_combustion_state() -> None:
    fp = SimpleNamespace(
        initial_conditions=SimpleNamespace(
            combustion_state=SimpleNamespace(
                resolved_burned_fraction_0to1=0.1,
                burned_mass_percent=10.0,
            )
        )
    )
    cylinder = SimpleNamespace(resolved_initial_burned_fraction_0to1=0.73)

    assert _initial_cylinder_burned_fraction_0to1(fp, cylinder) == pytest.approx(0.73)


def test_global_compatibility_combustion_state_uses_first_named_cylinder() -> None:
    lines = [
        "free_piston:\n",
        "  initial_conditions:\n",
        "    x0_m: 0.04\n",
        "    v0_m_per_s: -1.0\n",
        "    combustion_state:\n",
        "      burned_fraction_0to1: 0.0\n",
        "      burned_mass_percent: 0.0\n",
        "      released_energy_J: 0.0\n",
        "      ignition_armed: false\n",
        "      injection_armed: false\n",
        "modeling:\n",
        "  architecture: free_piston\n",
    ]
    sample = RestartStateSample(
        t_s=1.0,
        cycle_index=2,
        x_target_m=0.04,
        x_sample_m=0.04,
        v_sample_m_per_s=-2.0,
        start_sample_index=10,
        end_sample_index=11,
        columns={
            "cylinder_1_m_kg": 2.0,
            "cylinder_1_m_burned_kg": 0.5,
            "cylinder_2_m_kg": 2.0,
            "cylinder_2_m_burned_kg": 1.5,
        },
    )

    changed = _update_free_piston_initial_conditions(lines, sample, has_stateful_bounce=False)
    updated = "".join(lines)

    assert changed == 3
    assert "v0_m_per_s: -2.0" in updated
    assert "burned_fraction_0to1: 0.25" in updated
    assert "burned_mass_percent: 25.0" in updated
    assert "burned_fraction_0to1: 0.75" not in updated
