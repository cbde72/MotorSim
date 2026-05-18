from __future__ import annotations

import numba as nb

_QUELLEN_LAMBDA_MIN = 1.0
_QUELLEN_LAMBDA_MAX = 1000.0
_DEFAULT_AIRLIKE_LAMBDA = 1000.0
_DEFAULT_AFR_STOICH = 14.5
_DEFAULT_CV_FALLBACK = 718.0
_DEFAULT_TEMPERATURE_K = 300.0
_T_MIN_K = 200.0
_T_MAX_K = 4000.0
_EPS = 1.0e-18

_R_AIR = 287.05
_R_FUEL_VAPOR = 72.8
_R_BURNED = 289.0
_CP_AIR_300K = 1004.5
_CP_FUEL_VAPOR_300K = 1670.0
_CP_BURNED_300K = 1115.0


@nb.njit(cache=True)
def _clamp_temperature_K(temperature_K: float) -> float:
    if temperature_K < _T_MIN_K:
        return _T_MIN_K
    if temperature_K > _T_MAX_K:
        return _T_MAX_K
    return temperature_K


@nb.njit(cache=True)
def clamp_quellen_lambda(lambda_value: float) -> float:
    if lambda_value < _QUELLEN_LAMBDA_MIN:
        return _QUELLEN_LAMBDA_MIN
    if lambda_value > _QUELLEN_LAMBDA_MAX:
        return _QUELLEN_LAMBDA_MAX
    return lambda_value


@nb.njit(cache=True)
def default_airlike_lambda() -> float:
    return _DEFAULT_AIRLIKE_LAMBDA


@nb.njit(cache=True)
def lambda_from_total_and_fuel_mass(total_mass_kg: float, fuel_mass_kg: float, afr_stoich_kg_air_per_kg_fuel: float) -> float:
    fuel = fuel_mass_kg if fuel_mass_kg > 0.0 else 0.0
    afr = afr_stoich_kg_air_per_kg_fuel if afr_stoich_kg_air_per_kg_fuel > _EPS else _DEFAULT_AFR_STOICH
    if fuel <= _EPS:
        return _DEFAULT_AIRLIKE_LAMBDA
    lambda_value = (total_mass_kg - fuel) / (fuel * afr)
    return clamp_quellen_lambda(lambda_value)


@nb.njit(cache=True)
def lambda_from_air_and_fuel_mass(air_mass_kg: float, fuel_mass_kg: float, afr_stoich_kg_air_per_kg_fuel: float) -> float:
    fuel = fuel_mass_kg if fuel_mass_kg > 0.0 else 0.0
    afr = afr_stoich_kg_air_per_kg_fuel if afr_stoich_kg_air_per_kg_fuel > _EPS else _DEFAULT_AFR_STOICH
    if fuel <= _EPS:
        return _DEFAULT_AIRLIKE_LAMBDA
    lambda_value = max(air_mass_kg, 0.0) / (fuel * afr)
    return clamp_quellen_lambda(lambda_value)


@nb.njit(cache=True)
def gas_constant_from_lambda_quellen(lambda_value: float, afr_stoich_kg_air_per_kg_fuel: float) -> float:
    lam = clamp_quellen_lambda(lambda_value)
    rmst = afr_stoich_kg_air_per_kg_fuel if afr_stoich_kg_air_per_kg_fuel > _EPS else _DEFAULT_AFR_STOICH
    denom = 28.898 + (lam - 1.0) / (lam * rmst + 1.0)
    if denom <= _EPS:
        denom = 28.898
    return 8314.38 / denom


@nb.njit(cache=True)
def cv_from_lambda_temperature_quellen(lambda_value: float, temperature_K: float) -> float:
    lam = clamp_quellen_lambda(lambda_value)
    t_k = _clamp_temperature_K(temperature_K)
    t_c = t_k - 273.15
    cv = 144.71 * (
        -3.0 * (0.0975 + 0.0485 / (lam ** 0.75)) * (t_c * t_c) * 1.0e-6
        + 2.0 * (7.768 + 3.36 / (lam ** 0.8)) * t_c * 1.0e-4
        + (4.896 + 0.464 / (lam ** 0.93))
    )
    if cv < 1.0:
        return 1.0
    return cv


@nb.njit(cache=True)
def cp_from_lambda_temperature_quellen(lambda_value: float, temperature_K: float, afr_stoich_kg_air_per_kg_fuel: float) -> float:
    return cv_from_lambda_temperature_quellen(lambda_value, temperature_K) + gas_constant_from_lambda_quellen(lambda_value, afr_stoich_kg_air_per_kg_fuel)


@nb.njit(cache=True)
def kappa_from_lambda_temperature_quellen(lambda_value: float, temperature_K: float, afr_stoich_kg_air_per_kg_fuel: float) -> float:
    cv = cv_from_lambda_temperature_quellen(lambda_value, temperature_K)
    cp = cv + gas_constant_from_lambda_quellen(lambda_value, afr_stoich_kg_air_per_kg_fuel)
    return cp / cv


@nb.njit(cache=True)
def _cp_air_quellen_component(temperature_K: float) -> float:
    t = _clamp_temperature_K(temperature_K)
    dt = t - 300.0
    cp = _CP_AIR_300K + 0.08 * dt
    if cp < 900.0:
        return 900.0
    if cp > 1250.0:
        return 1250.0
    return cp


@nb.njit(cache=True)
def _cp_fuel_vapor_quellen_component(temperature_K: float) -> float:
    t = _clamp_temperature_K(temperature_K)
    dt = t - 300.0
    cp = _CP_FUEL_VAPOR_300K + 0.45 * dt
    if cp < 1400.0:
        return 1400.0
    if cp > 2800.0:
        return 2800.0
    return cp


@nb.njit(cache=True)
def _cp_burned_quellen_component(temperature_K: float) -> float:
    t = _clamp_temperature_K(temperature_K)
    dt = t - 300.0
    cp = _CP_BURNED_300K + 0.15 * dt
    if cp < 950.0:
        return 950.0
    if cp > 1700.0:
        return 1700.0
    return cp


@nb.njit(cache=True)
def _cv_air_quellen_component(temperature_K: float) -> float:
    cv = _cp_air_quellen_component(temperature_K) - _R_AIR
    if cv < 1.0:
        return 1.0
    return cv


@nb.njit(cache=True)
def _cv_fuel_vapor_quellen_component(temperature_K: float) -> float:
    cv = _cp_fuel_vapor_quellen_component(temperature_K) - _R_FUEL_VAPOR
    if cv < 1.0:
        return 1.0
    return cv


@nb.njit(cache=True)
def _cv_burned_quellen_component(temperature_K: float) -> float:
    cv = _cp_burned_quellen_component(temperature_K) - _R_BURNED
    if cv < 1.0:
        return 1.0
    return cv


@nb.njit(cache=True)
def reduced_mixture_properties_from_temperature_quellen(
    temperature_K: float,
    air_mass_kg: float,
    fuel_vapor_mass_kg: float,
    burned_mass_kg: float,
) -> tuple[float, float, float, float]:
    air = max(air_mass_kg, 0.0)
    fuel = max(fuel_vapor_mass_kg, 0.0)
    burned = max(burned_mass_kg, 0.0)
    total = air + fuel + burned
    if total <= _EPS:
        cv = _DEFAULT_CV_FALLBACK
        r = _R_AIR
        cp = cv + r
        return cp, cv, r, cp / cv
    cv_mix = (
        air * _cv_air_quellen_component(temperature_K)
        + fuel * _cv_fuel_vapor_quellen_component(temperature_K)
        + burned * _cv_burned_quellen_component(temperature_K)
    ) / total
    r_mix = (air * _R_AIR + fuel * _R_FUEL_VAPOR + burned * _R_BURNED) / total
    cp_mix = cv_mix + r_mix
    if cv_mix <= _EPS:
        cv_mix = _DEFAULT_CV_FALLBACK
        cp_mix = cv_mix + r_mix
    return cp_mix, cv_mix, r_mix, cp_mix / cv_mix


@nb.njit(cache=True)
def temperature_from_mass_energy_components_quellen(
    mass_kg: float,
    internal_energy_J: float,
    air_mass_kg: float,
    fuel_vapor_mass_kg: float,
    burned_mass_kg: float,
    cv_fallback_J_per_kgK: float,
) -> float:
    if mass_kg <= _EPS:
        return _DEFAULT_TEMPERATURE_K
    cv_fallback = cv_fallback_J_per_kgK if cv_fallback_J_per_kgK > _EPS else _DEFAULT_CV_FALLBACK
    temperature_K = internal_energy_J / (mass_kg * cv_fallback)
    if temperature_K < 1.0:
        temperature_K = 1.0
    for _ in range(10):
        _cp, cv_mix, _r, _kappa = reduced_mixture_properties_from_temperature_quellen(
            temperature_K,
            air_mass_kg,
            fuel_vapor_mass_kg,
            burned_mass_kg,
        )
        if cv_mix <= _EPS:
            break
        t_new = internal_energy_J / (mass_kg * cv_mix)
        if t_new < 1.0:
            t_new = 1.0
        temperature_K = 0.5 * temperature_K + 0.5 * t_new
    if temperature_K < 1.0:
        return 1.0
    return temperature_K


@nb.njit(cache=True)
def properties_from_mass_energy_components_quellen(
    mass_kg: float,
    internal_energy_J: float,
    air_mass_kg: float,
    fuel_vapor_mass_kg: float,
    burned_mass_kg: float,
    cv_fallback_J_per_kgK: float,
) -> tuple[float, float, float, float, float]:
    temperature_K = temperature_from_mass_energy_components_quellen(
        mass_kg,
        internal_energy_J,
        air_mass_kg,
        fuel_vapor_mass_kg,
        burned_mass_kg,
        cv_fallback_J_per_kgK,
    )
    cp_mix, cv_mix, gas_constant, kappa = reduced_mixture_properties_from_temperature_quellen(
        temperature_K,
        air_mass_kg,
        fuel_vapor_mass_kg,
        burned_mass_kg,
    )
    return temperature_K, cp_mix, cv_mix, gas_constant, kappa


@nb.njit(cache=True)
def pressure_from_mass_energy_components_quellen(
    mass_kg: float,
    internal_energy_J: float,
    volume_m3: float,
    air_mass_kg: float,
    fuel_vapor_mass_kg: float,
    burned_mass_kg: float,
    cv_fallback_J_per_kgK: float,
) -> float:
    if volume_m3 <= _EPS:
        return 1.0e3
    temperature_K, _cp, _cv, gas_constant, _kappa = properties_from_mass_energy_components_quellen(
        mass_kg,
        internal_energy_J,
        air_mass_kg,
        fuel_vapor_mass_kg,
        burned_mass_kg,
        cv_fallback_J_per_kgK,
    )
    pressure_Pa = mass_kg * gas_constant * temperature_K / volume_m3
    if pressure_Pa < 1.0:
        return 1.0
    return pressure_Pa


@nb.njit(cache=True)
def temperature_from_mass_energy_lambda_quellen(
    mass_kg: float,
    internal_energy_J: float,
    lambda_value: float,
    afr_stoich_kg_air_per_kg_fuel: float,
    cv_fallback_J_per_kgK: float,
) -> float:
    if mass_kg <= _EPS:
        return _DEFAULT_TEMPERATURE_K
    cv_fallback = cv_fallback_J_per_kgK if cv_fallback_J_per_kgK > _EPS else _DEFAULT_CV_FALLBACK
    temperature_K = internal_energy_J / (mass_kg * cv_fallback)
    if temperature_K < 1.0:
        temperature_K = 1.0
    lam = clamp_quellen_lambda(lambda_value)
    _afr = afr_stoich_kg_air_per_kg_fuel if afr_stoich_kg_air_per_kg_fuel > _EPS else _DEFAULT_AFR_STOICH
    for _ in range(8):
        cv = cv_from_lambda_temperature_quellen(lam, temperature_K)
        if cv <= _EPS:
            break
        t_new = internal_energy_J / (mass_kg * cv)
        if t_new < 1.0:
            t_new = 1.0
        temperature_K = 0.5 * temperature_K + 0.5 * t_new
    if temperature_K < 1.0:
        return 1.0
    return temperature_K


@nb.njit(cache=True)
def properties_from_mass_energy_lambda_quellen(
    mass_kg: float,
    internal_energy_J: float,
    lambda_value: float,
    afr_stoich_kg_air_per_kg_fuel: float,
    cv_fallback_J_per_kgK: float,
) -> tuple[float, float, float, float, float]:
    temperature_K = temperature_from_mass_energy_lambda_quellen(
        mass_kg,
        internal_energy_J,
        lambda_value,
        afr_stoich_kg_air_per_kg_fuel,
        cv_fallback_J_per_kgK,
    )
    gas_constant = gas_constant_from_lambda_quellen(lambda_value, afr_stoich_kg_air_per_kg_fuel)
    cv = cv_from_lambda_temperature_quellen(lambda_value, temperature_K)
    cp = cv + gas_constant
    kappa = cp / cv
    return temperature_K, cp, cv, gas_constant, kappa


@nb.njit(cache=True)
def pressure_from_mass_energy_lambda_quellen(
    mass_kg: float,
    internal_energy_J: float,
    volume_m3: float,
    lambda_value: float,
    afr_stoich_kg_air_per_kg_fuel: float,
    cv_fallback_J_per_kgK: float,
) -> float:
    if volume_m3 <= _EPS:
        return 1.0e3
    temperature_K, _cp, _cv, gas_constant, _kappa = properties_from_mass_energy_lambda_quellen(
        mass_kg,
        internal_energy_J,
        lambda_value,
        afr_stoich_kg_air_per_kg_fuel,
        cv_fallback_J_per_kgK,
    )
    pressure_Pa = mass_kg * gas_constant * temperature_K / volume_m3
    if pressure_Pa < 1.0:
        return 1.0
    return pressure_Pa
