from __future__ import annotations

import inspect

import numpy as np

from thermo0d.model.free_piston.combustion_latch import beck_2003_1_arrhenius_ignition_delay_s
from thermo0d.physics.beck import BECK_COOL_FLAME_FUEL_PARAMETERS, beck_cool_flame_fuel_parameters
from thermo0d.physics.combustion import vibe_beck_time_fraction_and_rate, vibe_beck_time_heat_release_rate_with_total_energy


def _tau(*, pressure_Pa: float = 4.0e6, air_mass_kg: float = 8.0e-4, burned_mass_kg: float = 0.0) -> float:
    return beck_2003_1_arrhenius_ignition_delay_s(
        c1_s=1.0e-5,
        c2=-1.2,
        reference_pressure_bar=1.0,
        reference_o2_percent=20.94,
        activation_energy_J_per_kg=0.0,
        activation_temperature_K=5000.0,
        pressure_Pa=pressure_Pa,
        temperature_K=850.0,
        volume_m3=4.0e-5,
        gas_mass_kg=air_mass_kg + burned_mass_kg,
        air_mass_kg=air_mass_kg,
        burned_mass_kg=burned_mass_kg,
    )


def test_beck_ignition_delay_gets_shorter_with_pressure() -> None:
    assert _tau(pressure_Pa=8.0e6) < _tau(pressure_Pa=4.0e6)


def test_beck_ignition_delay_gets_longer_with_lower_oxygen_concentration() -> None:
    no_residual = _tau(air_mass_kg=8.0e-4, burned_mass_kg=0.0)
    diluted = _tau(air_mass_kg=6.0e-4, burned_mass_kg=2.0e-4)

    assert diluted > no_residual
    assert np.isfinite(diluted)


def test_vibe_beck_time_heat_release_integrates_to_total_energy() -> None:
    q_total = 120.0
    t = np.linspace(0.0, 0.002, 2001)
    qdot = np.asarray([
        vibe_beck_time_heat_release_rate_with_total_energy(float(t_i), 0.0, 0.002, 6.9, 2.0, q_total)
        for t_i in t
    ])

    released = float(np.trapz(qdot, t))

    assert np.isclose(released, q_total, rtol=5.0e-3, atol=5.0e-2)


def test_vibe_beck_api_is_time_based_without_crank_angle_inputs() -> None:
    for fn in (vibe_beck_time_fraction_and_rate, vibe_beck_time_heat_release_rate_with_total_energy):
        names = set(inspect.signature(fn).parameters)

        assert {'t_s', 'soc_time_s', 'duration_s'} <= names
        assert not any('theta' in name or 'angle' in name or name.endswith('_deg') for name in names)


def test_beck_cool_flame_fuel_table_contains_dissertation_diesel_2_values() -> None:
    params = beck_cool_flame_fuel_parameters('Diesel 2')

    assert len(BECK_COOL_FLAME_FUEL_PARAMETERS) == 9
    assert params.hot_flame_activation_energy_J_per_kg == 2248e3
    assert params.hot_flame_activation_std_percent == 1.23
    assert params.cool_flame_activation_energy_J_per_kg == 1579e3
    assert params.cool_flame_activation_std_percent == 1.87
    assert params.dqmax == (0.363, 0.0, -0.333, 1.424, 0.155, 7.5e-3)
    assert params.dqmax_r2 == 0.963
    assert params.duration == (-0.071, -8.5e-3, 0.016, -0.241, -0.645, 340.9)
    assert params.duration_r2 == 0.967
