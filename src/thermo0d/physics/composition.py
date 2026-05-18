from __future__ import annotations

import numba as nb


@nb.njit(cache=True)
def clamp_burned_mass(total_mass_kg: float, burned_mass_kg: float) -> float:
    if burned_mass_kg <= 0.0:
        return 0.0
    if burned_mass_kg >= total_mass_kg:
        return max(total_mass_kg, 0.0)
    return burned_mass_kg


@nb.njit(cache=True)
def burned_fraction_0to1(total_mass_kg: float, burned_mass_kg: float) -> float:
    total = max(total_mass_kg, 0.0)
    if total <= 1.0e-18:
        return 0.0
    burned = clamp_burned_mass(total, burned_mass_kg)
    return burned / total


@nb.njit(cache=True)
def unburned_mass_kg(total_mass_kg: float, burned_mass_kg: float) -> float:
    total = max(total_mass_kg, 0.0)
    burned = clamp_burned_mass(total, burned_mass_kg)
    remaining = total - burned
    return remaining if remaining > 0.0 else 0.0


@nb.njit(cache=True)
def combustion_conversion_rate_kg_per_s(
    total_mass_kg: float,
    burned_mass_kg: float,
    xb_0to1: float,
    dxb_dt_1_per_s: float,
) -> float:
    if dxb_dt_1_per_s <= 0.0:
        return 0.0
    denom = 1.0 - min(max(xb_0to1, 0.0), 1.0)
    if denom <= 1.0e-12:
        return 0.0
    m_unburned = unburned_mass_kg(total_mass_kg, burned_mass_kg)
    if m_unburned <= 0.0:
        return 0.0
    omega = dxb_dt_1_per_s / denom
    return m_unburned * omega
