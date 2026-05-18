from __future__ import annotations

import numba as nb


@nb.njit(cache=True)
def safe_temperature_from_state(mass_kg: float, internal_energy_J: float, cv_J_per_kgK: float) -> float:
    if mass_kg <= 1.0e-18:
        return 300.0
    temperature_K = internal_energy_J / (mass_kg * cv_J_per_kgK)
    if temperature_K < 1.0:
        return 1.0
    return temperature_K


@nb.njit(cache=True)
def safe_pressure_from_ideal_gas(mass_kg: float, temperature_K: float, gas_constant_J_per_kgK: float, volume_m3: float) -> float:
    if volume_m3 <= 1.0e-18:
        return 1.0e3
    pressure_Pa = mass_kg * gas_constant_J_per_kgK * temperature_K / volume_m3
    if pressure_Pa < 1.0:
        return 1.0
    return pressure_Pa


def specific_internal_energy_from_temperature(temperature_K: float, cv_J_per_kgK: float) -> float:
    if temperature_K <= 0.0:
        raise ValueError('temperature_K must be > 0')
    if cv_J_per_kgK <= 0.0:
        raise ValueError('cv_J_per_kgK must be > 0')
    return float(cv_J_per_kgK * temperature_K)


def temperature_from_state(mass_kg: float, internal_energy_J: float, cv_J_per_kgK: float) -> float:
    if mass_kg <= 0.0:
        raise ValueError('mass_kg must be > 0')
    if internal_energy_J <= 0.0:
        raise ValueError('internal_energy_J must be > 0')
    if cv_J_per_kgK <= 0.0:
        raise ValueError('cv_J_per_kgK must be > 0')
    temperature_K = float(internal_energy_J / (mass_kg * cv_J_per_kgK))
    if temperature_K <= 0.0:
        raise ValueError('computed temperature_K must be > 0')
    return temperature_K


def pressure_from_state(mass_kg: float, internal_energy_J: float, volume_m3: float, gas_constant_J_per_kgK: float, cv_J_per_kgK: float) -> float:
    if volume_m3 <= 0.0:
        raise ValueError('volume_m3 must be > 0')
    if gas_constant_J_per_kgK <= 0.0:
        raise ValueError('gas_constant_J_per_kgK must be > 0')
    temperature_K = temperature_from_state(mass_kg, internal_energy_J, cv_J_per_kgK)
    pressure_Pa = float(mass_kg * gas_constant_J_per_kgK * temperature_K / volume_m3)
    if pressure_Pa <= 0.0:
        raise ValueError('computed pressure_Pa must be > 0')
    return pressure_Pa


def mass_from_pTV(pressure_Pa: float, temperature_K: float, volume_m3: float, gas_constant_J_per_kgK: float) -> float:
    if pressure_Pa <= 0.0:
        raise ValueError('pressure_Pa must be > 0')
    if temperature_K <= 0.0:
        raise ValueError('temperature_K must be > 0')
    if volume_m3 <= 0.0:
        raise ValueError('volume_m3 must be > 0')
    if gas_constant_J_per_kgK <= 0.0:
        raise ValueError('gas_constant_J_per_kgK must be > 0')
    mass_kg = float(pressure_Pa * volume_m3 / (gas_constant_J_per_kgK * temperature_K))
    if mass_kg <= 0.0:
        raise ValueError('computed mass_kg must be > 0')
    return mass_kg
