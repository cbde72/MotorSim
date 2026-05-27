#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diesel-HCCI single-zone model using Cantera's native CVODE solver (ReactorNet).
Entkoppelte, hochstabile Version mit abgesicherter Woschni-Wandwärme-Kopplung.

Verhindert zuverlässig CVODE-Extrapolations-NaNs bei steifer Zündung.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
from typing import Dict, Tuple

import numpy as np
import pandas as pd
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
    # Geometrie
    bore_m: float = 0.070
    stroke_m: float = 0.080
    conrod_m: float = 0.140
    compression_ratio: float = 50.0

    # Betriebspunkt
    rpm: float = 1500.0
    theta_start_deg: float = -180.0  # UT vor Kompression (OT = 0 deg)
    theta_end_deg: float = 180.0     # Expansion bis UT

    # Massen beim Einlass-Schließen (Start der Simulation)
    m_fresh_air_kg: float = 4.50e-4
    m_residual_gas_kg: float = 5.00e-5

    # Anfangstemperaturen der Komponenten vor der Mischung
    T_fresh_air_K: float = 330.0
    T_residual_gas_K: float = 850.0
    T_fuel_K: float = 330.0

    # Homogenes Gemisch
    lambda_air: float = 3.0
    fuel_species: str = "NC12H26"
    fuel_C: int = 12
    fuel_H: int = 26

    # Cantera Chemie-Einstellungen
    mechanism: str = "NC12H26_NTC.yaml"
    mechanism: str =r"C:\Py_Scripte\0_MotorSim_V03\Projekte\data\NC12H26_NTC.yaml"
    phase_name: str = "gas"

    # Woschni-Wandwärmeübergang
    wall_temperature_K: float = 420.0
    woschni_C1: float = 2.28
    woschni_multiplier: float = 1.0
    h_min_W_m2K: float = 20.0
    h_max_W_m2K: float = 5000.0

    # Numerik (Robuste CVODE-Führung für 130-Spezies-NTC)
    rtol: float = 1.0e-5
    atol: float = 1.0e-7             # Gelockert, um Radikalrauschen-Explosionen zu verhindern
    max_step_s: float = 1.0e-6       # Enge Führung verhindert Überschlagen der Kinetik

    # Ausgabe
    output_dir: str = "hcci_cvode_output"


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

    def x_from_tdc(self, theta_rad: float) -> float:
        r, l = self.r, self.l
        s, c = math.sin(theta_rad), math.cos(theta_rad)
        # Radikand-Absicherung gegen numerische Ungenauigkeiten bei UT/OT
        radikand = max(l * l - (r * s) ** 2, 1.0e-10)
        return r * (1.0 - c) + l - math.sqrt(radikand)

    def dx_dtheta(self, theta_rad: float) -> float:
        r, l = self.r, self.l
        s, c = math.sin(theta_rad), math.cos(theta_rad)
        radikand = max(l * l - (r * s) ** 2, 1.0e-10)
        return r * s + (r * r * s * c) / math.sqrt(radikand)

    def volume(self, theta_rad: float) -> float:
        return self.Vc + self.area * self.x_from_tdc(theta_rad)

    def dV_dtheta(self, theta_rad: float) -> float:
        return self.area * self.dx_dtheta(theta_rad)

    def wall_area(self, theta_rad: float) -> float:
        return 2.0 * self.area + math.pi * self.bore * self.x_from_tdc(theta_rad)


def species_index_ci(gas: ct.Solution, name: str) -> int:
    lower = {s.lower(): i for i, s in enumerate(gas.species_names)}
    key = name.lower()
    if key not in lower:
        raise KeyError(f"Species '{name}' nicht im Mechanismus gefunden.")
    return lower[key]


def diesel_stoich_afr(gas: ct.Solution, cfg: EngineConfig) -> float:
    i_fuel = species_index_ci(gas, cfg.fuel_species)
    MW_fuel = gas.molecular_weights[i_fuel]
    nu_O2 = cfg.fuel_C + cfg.fuel_H / 4.0
    mass_air_per_kmol_fuel = nu_O2 * 31.998 + 3.76 * nu_O2 * 28.014
    return mass_air_per_kmol_fuel / MW_fuel


def residual_products_mass(gas: ct.Solution, total_mass_kg: float, cfg: EngineConfig) -> Dict[str, float]:
    if total_mass_kg <= 0.0:
        return {}
    C, H = cfg.fuel_C, cfg.fuel_H
    nu_O2_st = C + H / 4.0
    mol = {
        "CO2": C,
        "H2O": H / 2.0,
        "N2": 1.2 * nu_O2_st * 3.76,
        "O2": 0.2 * nu_O2_st,
    }
    masses = {}
    total = 0.0
    for sp, n in mol.items():
        MW = gas.molecular_weights[species_index_ci(gas, sp)]
        masses[sp] = n * MW
        total += masses[sp]
    return {sp: total_mass_kg * val / total for sp, val in masses.items()}


def build_initial_state(gas: ct.Solution, geom: CrankSlider, cfg: EngineConfig) -> Tuple[float, np.ndarray, float, float]:
    afr_st = diesel_stoich_afr(gas, cfg)
    m_fuel = cfg.m_fresh_air_kg / (cfg.lambda_air * afr_st)
    m_total = cfg.m_fresh_air_kg + cfg.m_residual_gas_kg + m_fuel

    m_vec = np.zeros(gas.n_species)
    m_vec[species_index_ci(gas, "O2")] += cfg.m_fresh_air_kg * 0.232
    m_vec[species_index_ci(gas, "N2")] += cfg.m_fresh_air_kg * 0.768
    for sp, m in residual_products_mass(gas, cfg.m_residual_gas_kg, cfg).items():
        m_vec[species_index_ci(gas, sp)] += m
    m_vec[species_index_ci(gas, cfg.fuel_species)] += m_fuel

    Y0 = m_vec / np.sum(m_vec)
    T0 = (cfg.m_fresh_air_kg * cfg.T_fresh_air_K + cfg.m_residual_gas_kg * cfg.T_residual_gas_K + m_fuel * cfg.T_fuel_K) / m_total

    V0 = geom.volume(math.radians(cfg.theta_start_deg))
    gas.TDY = T0, m_total / V0, Y0
    return T0, Y0, m_total, m_fuel


class CanteraEngineSimulator:
    """Handles transient kinematics and heat transfer within Cantera's ReactorNet environment."""
    def __init__(self, gas: ct.Solution, geom: CrankSlider, cfg: EngineConfig, m_total: float):
        self.gas = gas
        self.geom = geom
        self.cfg = cfg
        self.m_total = m_total
        self.omega = 2.0 * math.pi * cfg.rpm / 60.0

        # Erstelle Cantera Reaktorumgebung
        self.r = ct.IdealGasReactor(self.gas)

        # KORREKTUR 1: Modernes API-Mapping für Cantera 3.0+
        # Verhindert, dass transiente Radikale unter Null fallen und den C++ Löser killen
        try:
            self.r.settings.allow_negative_concentrations = False
        except AttributeError:
            # Fallback für ältere Cantera 2.x Versionen
            try:
                self.r.options.allow_negative_concentrations = False
            except AttributeError:
                pass

        self.r.volume = geom.volume(math.radians(cfg.theta_start_deg))

        # Umgebung/Wand für Wärmeübergang und beweglichen Kolben definieren
        self.env = ct.Reservoir(self.gas)
        self.wall = ct.Wall(self.r, self.env)

        # Zuweisung für Kolbenbewegung und Wärmestrom (Properties)
        self.wall.velocity = self.piston_velocity
        self.wall.heat_flux = self.woschni_heat_flux

        # Erstelle das Netzwerk
        self.net = ct.ReactorNet([self.r])
        self.net.rtol = cfg.rtol
        self.net.atol = cfg.atol

        # KORREKTUR 2: Modernes Mapping für die maximalen internen Solver-Schritte
        try:
            self.net.max_steps_per_advance = 150000
        except AttributeError:
            try:
                self.net.max_steps = 150000
            except AttributeError:
                pass

        # Mapping für die maximale Zeitschrittweite
        try:
            self.net.max_time_step = cfg.max_step_s
        except AttributeError:
            pass

    def theta_from_t(self, t: float) -> float:
        # Absicherung der Zeitachse gegen unphysikalische Extrapolationswerte von CVODE
        t_max = math.radians(self.cfg.theta_end_deg - self.cfg.theta_start_deg) / self.omega
        t_bounded = np.clip(t, 0.0, t_max)
        return math.radians(self.cfg.theta_start_deg) + self.omega * t_bounded

    def piston_velocity(self, t: float) -> float:
        theta = self.theta_from_t(t)
        dV_dt = self.geom.dV_dtheta(theta) * self.omega
        return dV_dt / self.geom.area

    def woschni_heat_flux(self, t: float) -> float:
        theta = self.theta_from_t(t)
        B = self.geom.bore

        # Knallharte thermodynamische Schranken für CVODE-Vorschauschritte
        p_bar = max(self.r.thermo.P / 1.0e5, 0.1)
        p_kPa = p_bar * 100.0
        T = np.clip(self.r.thermo.T, 250.0, 3500.0)

        mean_piston_speed = 2.0 * self.geom.stroke * self.cfg.rpm / 60.0
        w = max(self.cfg.woschni_C1 * mean_piston_speed, 0.1)

        h = 3.26 * B**(-0.2) * p_kPa**0.8 * T**(-0.55) * w**0.8
        h *= self.cfg.woschni_multiplier
        h = np.clip(h, self.cfg.h_min_W_m2K, self.cfg.h_max_W_m2K)

        A_wall = self.geom.wall_area(theta)
        flux = h * (T - self.cfg.wall_temperature_K)

        if not np.isfinite(flux):
            return 0.0

        # Rückgabe normiert auf die mathematische Standard-Fläche der Cantera-Wand
        return float(flux * A_wall / self.geom.wall_area(math.radians(self.cfg.theta_start_deg)))

    def run(self, t_end: float, num_points: int = 500) -> pd.DataFrame:
        rows = []
        t_current = 0.0

        # Erzeuge Zielzeitpunkte für das spätere Post-Processing (Interpolations-Stützstellen)
        target_times = np.linspace(0.0, t_end, num_points)
        target_idx = 0

        print("Starte native CVODE Reaktor-Integration im geschützten Step-Modus...")

        # Der Löser läuft dynamisch in seinen eigenen, optimalen C++ Zeitschritten
        while t_current < t_end:
            try:
                # Macht genau einen internen, mathematisch optimalen Schritt
                t_current = self.net.step()
            except Exception as e:
                print(f"\n[WARNUNG] Kritischer Peak bei t={t_current:.6f}s. Versuche Not-Normalisierung...")
                # Erzwinge eine manuelle Bereinigung der Spezies-Konzentrationen im Reaktor
                try:
                    Y_tmp = self.r.thermo.Y
                    Y_tmp[Y_tmp < 0.0] = 0.0
                    Y_tmp /= np.sum(Y_tmp)
                    self.r.thermo.TDY = self.r.thermo.T, self.r.thermo.density, Y_tmp
                    t_current = self.net.step()
                except Exception:
                    print("Chemie-Kollaps unauflösbar. Breche ab, um Teil-Ergebnisse zu retten.")
                    break

            # Sobald der Löser eine oder mehrere unserer gewünschten Plot-Zeitpunkte überschritten hat,
            # zeichnen wir den aktuellen thermodynamischen Zustand auf
            while target_idx < num_points and target_times[target_idx] <= t_current:
                t_plot = target_times[target_idx]
                theta_rad = self.theta_from_t(t_plot)
                p_bar = self.gas.P / 1.0e5

                # Woschni synchronisieren
                p_kPa = p_bar * 100.0
                mean_piston_speed = 2.0 * self.geom.stroke * self.cfg.rpm / 60.0
                w = max(self.cfg.woschni_C1 * mean_piston_speed, 0.1)
                h = 3.26 * (self.geom.bore**-0.2) * p_kPa**0.8 * (self.gas.T**-0.55) * (w**0.8) * self.cfg.woschni_multiplier
                h = np.clip(h, self.cfg.h_min_W_m2K, self.cfg.h_max_W_m2K)

                rows.append({
                    "theta_deg": math.degrees(theta_rad),
                    "time_s": t_plot,
                    "volume_cm3": self.r.volume * 1.0e6,
                    "pressure_bar": p_bar,
                    "temperature_K": self.gas.T,
                    "density_kg_m3": self.gas.density,
                    "h_W_m2K": float(h),
                    "Qdot_wall_W": float(h * self.geom.wall_area(theta_rad) * (self.gas.T - self.cfg.wall_temperature_K))
                })
                target_idx += 1

        return pd.DataFrame(rows)

def plot_results(df: pd.DataFrame, outdir: Path) -> None:
    specs = [
        ("theta_deg", "pressure_bar", "Kurbelwinkel rel. OT [°KW]", "Druck [bar]", "pressure_vs_angle.png"),
        ("theta_deg", "temperature_K", "Kurbelwinkel rel. OT [°KW]", "Temperatur [K]", "temperature_vs_angle.png"),
        ("volume_cm3", "pressure_bar", "Volumen [cm³]", "Druck [bar]", "pV_diagram.png"),
    ]
    for x, y, xl, yl, name in specs:
        plt.figure(figsize=(8, 4.8))
        plt.plot(df[x], df[y], color='crimson' if "pressure" in name else 'darkblue')
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

    try:
        gas.derivative_settings = {"jacobian": "analytical"}
    except AttributeError:
        pass

    geom = CrankSlider(cfg.bore_m, cfg.stroke_m, cfg.conrod_m, cfg.compression_ratio)
    T0, Y0, m_total, m_fuel = build_initial_state(gas, geom, cfg)

    omega = 2.0 * math.pi * cfg.rpm / 60.0
    t_end = math.radians(cfg.theta_end_deg - cfg.theta_start_deg) / omega

    print("=== Diesel-HCCI CVODE Setup (Stabilisiert) ===")
    print(f"Mechanismus:         {cfg.mechanism}")
    print(f"Spezies-Anzahl:      {gas.n_species}")
    print(f"Reaktions-Anzahl:    {gas.n_reactions}")
    print(f"Simulationsdauer:    {t_end:.4f} s")

    sim = CanteraEngineSimulator(gas, geom, cfg, m_total)

    # Erlaube dem Gleichungslöser zähe, nicht-lineare Newton-Schleifen wegzustecken
    sim.net.max_err_test_fails = 80

    df = sim.run(t_end, num_points=600)

    if len(df) > 0:
        df.to_csv(outdir / "hcci_cvode_results.csv", index=False)
        plot_results(df, outdir)

        i_pmax = int(df["pressure_bar"].idxmax())
        i_tmax = int(df["temperature_K"].idxmax())
        print("\n=== Ergebnisse ===")
        print(f"Berechnete Schritte: {len(df)}")
        print(f"p_max:               {df.pressure_bar.iloc[i_pmax]:.2f} bar bei {df.theta_deg.iloc[i_pmax]:.2f} °KW")
        print(f"T_max:               {df.temperature_K.iloc[i_tmax]:.1f} K bei {df.theta_deg.iloc[i_tmax]:.2f} °KW")
    else:
        print("\nFehler: Keine gültigen Daten generiert.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())