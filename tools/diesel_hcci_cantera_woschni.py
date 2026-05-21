#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diesel-HCCI single-zone model with Cantera, crank-slider compression and
Woschni-like wall heat transfer.

Scope
-----
- Closed cylinder after intake valve closing / start of compression
- No valves, no injection during simulation, no blow-by
- Homogeneous diesel-surrogate / fresh-air / residual-gas mixture
- CR = 50, bore = 70 mm by default
- Stroke, masses, lambda and temperatures are configurable
- Cantera finite-rate chemistry
- Woschni-like wall heat transfer
- CSV + PNG outputs

Recommended mechanism
---------------------
Use a diesel-surrogate mechanism, e.g. nDodecane_Reitz.yaml.
If your mechanism uses another fuel species name, change CFG.fuel_species.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
from typing import Dict, Tuple

import numpy as np
import pandas as pd
from scipy.integrate import solve_ivp
import matplotlib.pyplot as plt

try:
    import cantera as ct
except ImportError as exc:
    raise SystemExit(
        "Cantera is not installed in the active Python environment.\n"
        "Install example:\n"
        "    conda install -c conda-forge cantera\n"
        "or:\n"
        "    pip install cantera\n"
    ) from exc


@dataclass
class EngineConfig:
    # Geometry
    bore_m: float = 0.070
    stroke_m: float = 0.080          # EDIT if your real stroke is different
    conrod_m: float = 0.140
    compression_ratio: float = 50.0

    # Operation
    rpm: float = 1500.0
    theta_start_deg: float = -180.0  # BDC before compression, TDC = 0 deg
    theta_end_deg: float = 180.0     # expansion to BDC

    # Initial masses at intake-valve closing / start of compression
    m_fresh_air_kg: float = 4.50e-4
    m_residual_gas_kg: float = 5.00e-5

    # Initial component temperatures before mixing
    T_fresh_air_K: float = 330.0
    T_residual_gas_K: float = 850.0
    T_fuel_K: float = 330.0

    # Homogeneous diesel-HCCI mixture
    lambda_air: float = 3.0
    fuel_species: str = "c12h26"     # n-dodecane in many mechanisms
    fuel_C: int = 12
    fuel_H: int = 26

    # Cantera chemistry
    mechanism: str = "nDodecane_Reitz.yaml"

    # Woschni-like wall heat transfer
    wall_temperature_K: float = 420.0
    woschni_C1: float = 2.28
    woschni_multiplier: float = 1.0
    h_min_W_m2K: float = 20.0
    h_max_W_m2K: float = 5000.0

    # Numerics
    rtol: float = 1.0e-6
    atol_T: float = 1.0e-3
    atol_Y: float = 1.0e-14
    max_step_deg: float = 0.05

    # Output
    output_dir: str = "hcci_output"
    phase_name: str = "nDodecane_RK"


CFG = EngineConfig()


class CrankSlider:
    def __init__(self, bore_m: float, stroke_m: float, conrod_m: float, cr: float):
        self.bore = bore_m
        self.stroke = stroke_m
        self.conrod = conrod_m
        self.cr = cr
        self.area = math.pi * bore_m ** 2 / 4.0
        self.r = stroke_m / 2.0
        self.l = conrod_m
        self.Vs = self.area * stroke_m
        self.Vc = self.Vs / (cr - 1.0)
        if self.l <= self.r:
            raise ValueError("conrod_m must be larger than stroke_m/2.")

    def x_from_tdc(self, theta_rad: float) -> float:
        r, l = self.r, self.l
        s, c = math.sin(theta_rad), math.cos(theta_rad)
        return r * (1.0 - c) + l - math.sqrt(l * l - (r * s) ** 2)

    def dx_dtheta(self, theta_rad: float) -> float:
        r, l = self.r, self.l
        s, c = math.sin(theta_rad), math.cos(theta_rad)
        root = math.sqrt(l * l - (r * s) ** 2)
        return r * s + (r * r * s * c) / root

    def volume(self, theta_rad: float) -> float:
        return self.Vc + self.area * self.x_from_tdc(theta_rad)

    def dV_dtheta(self, theta_rad: float) -> float:
        return self.area * self.dx_dtheta(theta_rad)

    def wall_area(self, theta_rad: float) -> float:
        x = self.x_from_tdc(theta_rad)
        return 2.0 * self.area + math.pi * self.bore * x


def species_index_ci(gas: ct.Solution, name: str) -> int:
    lower = {s.lower(): i for i, s in enumerate(gas.species_names)}
    key = name.lower()
    if key not in lower:
        raise KeyError(
            f"Species '{name}' not found in mechanism.\n"
            f"First available species: {gas.species_names[:50]}"
        )
    return lower[key]


def add_mass(m_vec: np.ndarray, gas: ct.Solution, species: str, mass_kg: float) -> None:
    if mass_kg == 0.0:
        return
    m_vec[species_index_ci(gas, species)] += mass_kg


def diesel_stoich_afr(gas: ct.Solution, cfg: EngineConfig) -> float:
    """Stoichiometric air/fuel mass ratio for CxHy with air = O2 + 3.76 N2."""
    i_fuel = species_index_ci(gas, cfg.fuel_species)
    MW_fuel = gas.molecular_weights[i_fuel]  # kg/kmol, numerically g/mol
    nu_O2 = cfg.fuel_C + cfg.fuel_H / 4.0
    mass_air_per_kmol_fuel = nu_O2 * 31.998 + 3.76 * nu_O2 * 28.014
    return mass_air_per_kmol_fuel / MW_fuel


def residual_products_mass(gas: ct.Solution, total_mass_kg: float, cfg: EngineConfig, residual_lambda: float = 1.2) -> Dict[str, float]:
    """Simplified lean-burn residual gas: CO2 + H2O + N2 + remaining O2."""
    if total_mass_kg <= 0.0:
        return {}
    C, H = cfg.fuel_C, cfg.fuel_H
    nu_O2_st = C + H / 4.0
    mol = {
        "CO2": C,
        "H2O": H / 2.0,
        "N2": residual_lambda * nu_O2_st * 3.76,
        "O2": max(0.0, (residual_lambda - 1.0) * nu_O2_st),
    }
    masses = {}
    total = 0.0
    for sp, n in mol.items():
        MW = gas.molecular_weights[species_index_ci(gas, sp)]
        masses[sp] = n * MW
        total += masses[sp]
    return {sp: total_mass_kg * val / total for sp, val in masses.items()}


def build_initial_state(gas: ct.Solution, geom: CrankSlider, cfg: EngineConfig) -> Tuple[float, np.ndarray, float, float, float]:
    afr_st = diesel_stoich_afr(gas, cfg)
    m_fuel = cfg.m_fresh_air_kg / (cfg.lambda_air * afr_st)
    m_total = cfg.m_fresh_air_kg + cfg.m_residual_gas_kg + m_fuel

    m_vec = np.zeros(gas.n_species)
    add_mass(m_vec, gas, "O2", cfg.m_fresh_air_kg * 0.232)
    add_mass(m_vec, gas, "N2", cfg.m_fresh_air_kg * 0.768)
    for sp, m in residual_products_mass(gas, cfg.m_residual_gas_kg, cfg).items():
        add_mass(m_vec, gas, sp, m)
    add_mass(m_vec, gas, cfg.fuel_species, m_fuel)

    Y0 = m_vec / np.sum(m_vec)
    T0 = (
        cfg.m_fresh_air_kg * cfg.T_fresh_air_K
        + cfg.m_residual_gas_kg * cfg.T_residual_gas_K
        + m_fuel * cfg.T_fuel_K
    ) / m_total

    V0 = geom.volume(math.radians(cfg.theta_start_deg))
    rho0 = m_total / V0
    gas.TDY = T0, rho0, Y0
    p0 = gas.P
    return T0, Y0, p0, m_total, m_fuel


def woschni_h(gas: ct.Solution, geom: CrankSlider, cfg: EngineConfig) -> float:
    """
    Simplified Woschni correlation:
        h = 3.26 * B^-0.2 * p_kPa^0.8 * T^-0.55 * w^0.8
    Gas velocity w is approximated from mean piston speed.
    """
    B = geom.bore
    p_kPa = max(gas.P / 1000.0, 1.0)
    T = max(gas.T, 250.0)
    mean_piston_speed = 2.0 * geom.stroke * cfg.rpm / 60.0
    w = max(cfg.woschni_C1 * mean_piston_speed, 0.1)
    h = 3.26 * B ** (-0.2) * p_kPa ** 0.8 * T ** (-0.55) * w ** 0.8
    h *= cfg.woschni_multiplier
    return float(np.clip(h, cfg.h_min_W_m2K, cfg.h_max_W_m2K))


def make_rhs(gas: ct.Solution, geom: CrankSlider, cfg: EngineConfig, m_total: float):
    MW = gas.molecular_weights
    omega = 2.0 * math.pi * cfg.rpm / 60.0

    def rhs(theta_rad: float, y: np.ndarray) -> np.ndarray:
        T = max(float(y[0]), 250.0)
        Y = np.maximum(y[1:], 0.0)
        Y /= np.sum(Y)

        V = geom.volume(theta_rad)
        rho = m_total / V
        gas.TDY = T, rho, Y

        wdot = gas.net_production_rates         # kmol/m3/s
        dYdt = wdot * MW / rho                  # 1/s
        dYdt -= Y * np.sum(dYdt)                # conservation correction

        u_mass = gas.partial_molar_int_energies / MW  # J/kg species
        chem_u_term = V * np.dot(u_mass * MW, wdot)   # J/s

        dVdt = geom.dV_dtheta(theta_rad) * omega
        h = woschni_h(gas, geom, cfg)
        A_wall = geom.wall_area(theta_rad)
        Qdot_wall = h * A_wall * (T - cfg.wall_temperature_K)

        dTdt = (-gas.P * dVdt - Qdot_wall - chem_u_term) / (m_total * gas.cv_mass)

        out = np.empty_like(y)
        out[0] = dTdt / omega
        out[1:] = dYdt / omega
        return out

    return rhs


def derived_dataframe(sol, gas: ct.Solution, geom: CrankSlider, cfg: EngineConfig, m_total: float) -> pd.DataFrame:
    rows = []
    omega = 2.0 * math.pi * cfg.rpm / 60.0
    for i, theta in enumerate(sol.t):
        T = sol.y[0, i]
        Y = np.maximum(sol.y[1:, i], 0.0)
        Y /= np.sum(Y)
        V = geom.volume(theta)
        gas.TDY = T, m_total / V, Y
        h = woschni_h(gas, geom, cfg)
        A = geom.wall_area(theta)
        rows.append({
            "theta_deg": math.degrees(theta),
            "time_s": (theta - math.radians(cfg.theta_start_deg)) / omega,
            "volume_cm3": V * 1.0e6,
            "pressure_bar": gas.P / 1.0e5,
            "temperature_K": gas.T,
            "density_kg_m3": gas.density,
            "h_W_m2K": h,
            "wall_area_m2": A,
            "Qdot_wall_W": h * A * (gas.T - cfg.wall_temperature_K),
        })
    return pd.DataFrame(rows)


def plot_results(df: pd.DataFrame, outdir: Path) -> None:
    specs = [
        ("theta_deg", "pressure_bar", "Crank angle rel. TDC [deg]", "Pressure [bar]", "pressure_vs_angle.png"),
        ("theta_deg", "temperature_K", "Crank angle rel. TDC [deg]", "Temperature [K]", "temperature_vs_angle.png"),
        ("volume_cm3", "pressure_bar", "Volume [cm³]", "Pressure [bar]", "pV_diagram.png"),
        ("theta_deg", "Qdot_wall_W", "Crank angle rel. TDC [deg]", "Wall heat loss [W]", "wall_heat_loss.png"),
    ]
    for x, y, xl, yl, name in specs:
        plt.figure(figsize=(8, 4.8))
        plt.plot(df[x], df[y])
        plt.xlabel(xl)
        plt.ylabel(yl)
        plt.grid(True, alpha=0.3)
        plt.tight_layout()
        plt.savefig(outdir / name, dpi=180)
        plt.close()


def main(cfg: EngineConfig = CFG) -> int:
    outdir = Path(cfg.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    gas = ct.Solution(cfg.mechanism, cfg.phase_name)
    geom = CrankSlider(cfg.bore_m, cfg.stroke_m, cfg.conrod_m, cfg.compression_ratio)
    T0, Y0, p0, m_total, m_fuel = build_initial_state(gas, geom, cfg)

    y0 = np.r_[T0, Y0]
    atol = np.r_[cfg.atol_T, np.full(gas.n_species, cfg.atol_Y)]

    print("=== Diesel-HCCI setup ===")
    print(f"Mechanism:         {cfg.mechanism}")
    print(f"Fuel species:      {cfg.fuel_species}")
    print(f"Bore:              {cfg.bore_m*1000:.1f} mm")
    print(f"Stroke:            {cfg.stroke_m*1000:.1f} mm")
    print(f"CR:                {cfg.compression_ratio:.1f}")
    print(f"Swept volume:      {geom.Vs*1e6:.2f} cm³")
    print(f"Clearance volume:  {geom.Vc*1e6:.2f} cm³")
    print(f"Fresh air mass:    {cfg.m_fresh_air_kg*1e6:.2f} mg")
    print(f"Residual gas mass: {cfg.m_residual_gas_kg*1e6:.2f} mg")
    print(f"Fuel mass:         {m_fuel*1e6:.3f} mg")
    print(f"Lambda:            {cfg.lambda_air:.2f}")
    print(f"Initial T:         {T0:.1f} K")
    print(f"Initial p:         {p0/1e5:.3f} bar")

    rhs = make_rhs(gas, geom, cfg, m_total)
    sol = solve_ivp(
        rhs,
        (math.radians(cfg.theta_start_deg), math.radians(cfg.theta_end_deg)),
        y0,
        method="BDF",
        rtol=cfg.rtol,
        atol=atol,
        max_step=math.radians(cfg.max_step_deg),
    )

    if not sol.success:
        print("WARNING: solver did not fully converge:")
        print(sol.message)

    df = derived_dataframe(sol, gas, geom, cfg, m_total)
    df.to_csv(outdir / "hcci_results.csv", index=False)
    plot_results(df, outdir)

    i_pmax = int(df["pressure_bar"].idxmax())
    i_tmax = int(df["temperature_K"].idxmax())
    print("=== Results ===")
    print(f"Solver success:    {sol.success}")
    print(f"Steps:             {len(sol.t)}")
    print(f"p_max:             {df.pressure_bar.iloc[i_pmax]:.2f} bar at {df.theta_deg.iloc[i_pmax]:.2f} deg")
    print(f"T_max:             {df.temperature_K.iloc[i_tmax]:.1f} K at {df.theta_deg.iloc[i_tmax]:.2f} deg")
    print(f"Final p:           {df.pressure_bar.iloc[-1]:.2f} bar")
    print(f"Final T:           {df.temperature_K.iloc[-1]:.1f} K")
    print(f"Output:            {outdir.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
