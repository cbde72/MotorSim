#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diesel-HCCI Single-Zone Cantera Modell
=====================================

Robuste, geschlossene 0D-HCCI-Rechnung mit:
- Cantera IdealGasReactor
- beweglichem Kolben ueber Wall.velocity
- Woschni-aehnlichem Wandwaermeverlust
- kontrollierter advance()-Integration zu festen Zielzeiten
- CSV-Ausgabe auch bei Teilabbruch
- Druck, Temperatur, p-V, HRR und MFB-Plots
- SOC, CA10, CA50, CA90 Auswertung

Wichtig:
- Der Kraftstoff ist am Start homogen vorgemischt.
- Es gibt keine Einspritzung waehrend der Simulation.
- Das Modell ist ein Single-Zone-Modell: ueberall gleicher Druck, gleiche Temperatur, gleiche Zusammensetzung.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import math
from typing import Dict, Tuple, Optional

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

try:
    import cantera as ct
except ImportError as exc:
    raise SystemExit(
        "Cantera ist in der aktiven Python-Umgebung nicht installiert.\n"
        "Installation z. B.:\n"
        "    conda install -c conda-forge cantera\n"
        "oder:\n"
        "    pip install cantera\n"
    ) from exc


@dataclass
class EngineConfig:
    # -------------------------------------------------------------------------
    # Geometrie
    # -------------------------------------------------------------------------
    bore_m: float = 0.070
    stroke_m: float = 0.080
    conrod_m: float = 0.140

    # Entschaerft gegenueber 50:1, weil 50:1 bei HCCI extrem harte Zuendung erzeugt.
    compression_ratio: float = 18.0

    # -------------------------------------------------------------------------
    # Betriebspunkt
    # theta = 0 deg entspricht OT, -180 deg UT vor Verdichtung, +180 deg UT nach Expansion
    # -------------------------------------------------------------------------
    rpm: float = 800.0
    theta_start_deg: float = -180.0
    theta_end_deg: float = 180.0

    # -------------------------------------------------------------------------
    # Masse / Zustand bei IVC bzw. Simulationsstart
    # -------------------------------------------------------------------------
    m_fresh_air_kg: float = 4.50e-4
    m_residual_gas_kg: float = 5.00e-5

    T_fresh_air_K: float = 330.0
    T_residual_gas_K: float = 650.0
    T_fuel_K: float = 330.0

    # Magerer Betrieb reduziert die chemische Haerte.
    lambda_air: float = 5.0

    # -------------------------------------------------------------------------
    # Kraftstoff / Mechanismus
    # -------------------------------------------------------------------------
    fuel_species: str = "NC12H26"
    fuel_C: int = 12
    fuel_H: int = 26

    mechanism: str = r"C:\Py_Scripte\0_MotorSim_V03\Projekte\data\NC12H26_NTC.yaml"
    phase_name: str = "gas"

    # -------------------------------------------------------------------------
    # Wandwaermeuebergang
    # -------------------------------------------------------------------------
    wall_temperature_K: float = 360.0
    woschni_C1: float = 2.28
    woschni_multiplier: float = 2.5
    h_min_W_m2K: float = 20.0
    h_max_W_m2K: float = 8000.0

    # -------------------------------------------------------------------------
    # Numerik
    # -------------------------------------------------------------------------
    rtol: float = 1.0e-4
    atol: float = 1.0e-10
    max_time_step_s: float = 2.0e-6
    max_err_test_fails: int = 100
    max_steps_per_advance: int = 200000

    # Feste Ausgabestellen. Mehr Punkte = glattere Plots, aber langsamer.
    num_output_points: int = 1200

    # Sicherheitsabbruch, wenn Temperatur oder Druck unphysikalisch hoch werden.
    max_temperature_K: float = 3500.0
    max_pressure_bar: float = 300.0

    # -------------------------------------------------------------------------
    # Ausgabe
    # -------------------------------------------------------------------------
    output_dir: str = "hcci_cvode_output"
    show_plots: bool = True
    save_plots: bool = True
    dpi: int = 180


CFG = EngineConfig()


class CrankSlider:
    def __init__(self, bore_m: float, stroke_m: float, conrod_m: float, cr: float):
        if cr <= 1.0:
            raise ValueError("compression_ratio muss > 1 sein.")
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
        rad = max(l * l - (r * s) ** 2, 1.0e-14)
        return r * (1.0 - c) + l - math.sqrt(rad)

    def dx_dtheta(self, theta_rad: float) -> float:
        r, l = self.r, self.l
        s, c = math.sin(theta_rad), math.cos(theta_rad)
        rad = max(l * l - (r * s) ** 2, 1.0e-14)
        return r * s + (r * r * s * c) / math.sqrt(rad)

    def volume(self, theta_rad: float) -> float:
        return self.Vc + self.area * self.x_from_tdc(theta_rad)

    def dV_dtheta(self, theta_rad: float) -> float:
        return self.area * self.dx_dtheta(theta_rad)

    def wall_area(self, theta_rad: float) -> float:
        return 2.0 * self.area + math.pi * self.bore * self.x_from_tdc(theta_rad)


# -----------------------------------------------------------------------------
# Hilfsfunktionen
# -----------------------------------------------------------------------------

def species_index_ci(gas: ct.Solution, name: str) -> int:
    lower = {s.lower(): i for i, s in enumerate(gas.species_names)}
    key = name.lower()
    if key not in lower:
        available = ", ".join(gas.species_names[:30])
        raise KeyError(
            f"Spezies '{name}' wurde im Mechanismus nicht gefunden. "
            f"Erste verfuegbare Spezies: {available} ..."
        )
    return lower[key]


def diesel_stoich_afr(gas: ct.Solution, cfg: EngineConfig) -> float:
    i_fuel = species_index_ci(gas, cfg.fuel_species)
    MW_fuel = gas.molecular_weights[i_fuel]  # kg/kmol in Cantera-Konvention
    nu_O2 = cfg.fuel_C + cfg.fuel_H / 4.0
    mass_air_per_kmol_fuel = nu_O2 * 31.998 + 3.76 * nu_O2 * 28.014
    return mass_air_per_kmol_fuel / MW_fuel


def residual_products_mass(gas: ct.Solution, total_mass_kg: float, cfg: EngineConfig) -> Dict[str, float]:
    """Einfaches Restgas als CO2/H2O/N2/O2-Gemisch."""
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


def build_initial_state(gas: ct.Solution, geom: CrankSlider, cfg: EngineConfig) -> Tuple[float, np.ndarray, float, float, float]:
    afr_st = diesel_stoich_afr(gas, cfg)
    m_fuel = cfg.m_fresh_air_kg / (cfg.lambda_air * afr_st)
    m_total = cfg.m_fresh_air_kg + cfg.m_residual_gas_kg + m_fuel

    m_vec = np.zeros(gas.n_species)
    m_vec[species_index_ci(gas, "O2")] += cfg.m_fresh_air_kg * 0.232
    m_vec[species_index_ci(gas, "N2")] += cfg.m_fresh_air_kg * 0.768

    for sp, m in residual_products_mass(gas, cfg.m_residual_gas_kg, cfg).items():
        m_vec[species_index_ci(gas, sp)] += m

    m_vec[species_index_ci(gas, cfg.fuel_species)] += m_fuel

    sum_m = float(np.sum(m_vec))
    if sum_m <= 0.0:
        raise ValueError("Initiale Gesamtmasse ist <= 0.")

    Y0 = m_vec / sum_m
    T0 = (
        cfg.m_fresh_air_kg * cfg.T_fresh_air_K
        + cfg.m_residual_gas_kg * cfg.T_residual_gas_K
        + m_fuel * cfg.T_fuel_K
    ) / m_total

    V0 = geom.volume(math.radians(cfg.theta_start_deg))
    rho0 = m_total / V0
    gas.TDY = T0, rho0, Y0

    return T0, Y0, m_total, m_fuel, afr_st


def safe_set_reactor_options(reactor: ct.IdealGasReactor) -> None:
    # API ist zwischen Cantera-Versionen leicht verschieden.
    for attr_chain in (
        ("settings", "allow_negative_concentrations"),
        ("options", "allow_negative_concentrations"),
    ):
        try:
            obj = getattr(reactor, attr_chain[0])
            setattr(obj, attr_chain[1], False)
        except Exception:
            pass


def reaction_heat_release_W_per_m3(gas: ct.Solution) -> float:
    """
    Chemische volumetrische Waermefreisetzung.

    Cantera:
    partial_molar_enthalpies: J/kmol
    net_production_rates: kmol/m3/s
    Summe h_k * wdot_k: J/m3/s = W/m3

    Bei exothermer Reaktion ist -sum(h*wdot) positiv.
    """
    qdot = -float(np.dot(gas.partial_molar_enthalpies, gas.net_production_rates))
    if not np.isfinite(qdot):
        return 0.0
    return qdot


def cumulative_trapezoid(y: np.ndarray, x: np.ndarray) -> np.ndarray:
    out = np.zeros_like(y, dtype=float)
    if len(y) < 2:
        return out
    dx = np.diff(x)
    avg = 0.5 * (y[1:] + y[:-1])
    out[1:] = np.cumsum(avg * dx)
    return out


def find_ca_from_mfb(df: pd.DataFrame, target: float) -> Optional[float]:
    if df.empty or "mfb" not in df.columns:
        return None
    arr = df["mfb"].to_numpy(dtype=float)
    theta = df["theta_deg"].to_numpy(dtype=float)
    valid = np.isfinite(arr) & np.isfinite(theta)
    if not np.any(valid):
        return None
    arr = arr[valid]
    theta = theta[valid]
    if np.nanmax(arr) < target:
        return None
    idx = int(np.nanargmin(np.abs(arr - target)))
    return float(theta[idx])


# -----------------------------------------------------------------------------
# Simulator
# -----------------------------------------------------------------------------

class CanteraEngineSimulator:
    def __init__(self, gas: ct.Solution, geom: CrankSlider, cfg: EngineConfig):
        self.gas = gas
        self.geom = geom
        self.cfg = cfg
        self.omega = 2.0 * math.pi * cfg.rpm / 60.0
        self.t_end = math.radians(cfg.theta_end_deg - cfg.theta_start_deg) / self.omega

        self.r = ct.IdealGasReactor(self.gas)
        safe_set_reactor_options(self.r)
        self.r.volume = geom.volume(math.radians(cfg.theta_start_deg))

        # Umgebung: inert genug, nur als Wandpartner. Zustand identisch initialisiert.
        self.env = ct.Reservoir(self.gas)
        self.wall = ct.Wall(self.r, self.env)
        self.wall.velocity = self.piston_velocity
        self.wall.heat_flux = self.woschni_heat_flux

        self.net = ct.ReactorNet([self.r])
        self.net.rtol = cfg.rtol
        self.net.atol = cfg.atol

        try:
            self.net.max_time_step = cfg.max_time_step_s
        except Exception:
            pass

        for attr, value in (
            ("max_err_test_fails", cfg.max_err_test_fails),
            ("max_steps_per_advance", cfg.max_steps_per_advance),
            ("max_steps", cfg.max_steps_per_advance),
        ):
            try:
                setattr(self.net, attr, value)
            except Exception:
                pass

    def theta_from_t(self, t: float) -> float:
        t_bounded = float(np.clip(t, 0.0, self.t_end))
        return math.radians(self.cfg.theta_start_deg) + self.omega * t_bounded

    def piston_velocity(self, t: float) -> float:
        theta = self.theta_from_t(t)
        dV_dt = self.geom.dV_dtheta(theta) * self.omega
        return dV_dt / self.geom.area

    def current_woschni_h(self, theta_rad: float) -> float:
        p_bar = max(self.r.thermo.P / 1.0e5, 0.1)
        p_kPa = p_bar * 100.0
        T = float(np.clip(self.r.thermo.T, 250.0, self.cfg.max_temperature_K))
        mean_piston_speed = 2.0 * self.geom.stroke * self.cfg.rpm / 60.0
        w = max(self.cfg.woschni_C1 * mean_piston_speed, 0.1)

        h = 3.26 * self.geom.bore ** (-0.2) * p_kPa ** 0.8 * T ** (-0.55) * w ** 0.8
        h *= self.cfg.woschni_multiplier
        h = float(np.clip(h, self.cfg.h_min_W_m2K, self.cfg.h_max_W_m2K))
        return h

    def woschni_heat_flux(self, t: float) -> float:
        theta = self.theta_from_t(t)
        T = float(np.clip(self.r.thermo.T, 250.0, self.cfg.max_temperature_K))
        h = self.current_woschni_h(theta)
        A_wall = self.geom.wall_area(theta)
        A_ref = max(self.geom.wall_area(math.radians(self.cfg.theta_start_deg)), 1.0e-12)

        # Cantera Wall.heat_flux ist W/m2 bezogen auf die Cantera-Wandflaeche.
        # Da hier keine echte Flaeche gesetzt wird, normieren wir auf A_ref.
        flux = h * (T - self.cfg.wall_temperature_K) * A_wall / A_ref
        if not np.isfinite(flux):
            return 0.0
        return float(flux)

    def collect_row(self, t_plot: float) -> Dict[str, float]:
        theta_rad = self.theta_from_t(t_plot)
        gas = self.r.thermo
        V = self.r.volume
        p_bar = gas.P / 1.0e5
        T = gas.T
        h = self.current_woschni_h(theta_rad)
        A_wall = self.geom.wall_area(theta_rad)
        Qdot_wall_W = h * A_wall * (T - self.cfg.wall_temperature_K)
        hrr_W_m3 = reaction_heat_release_W_per_m3(gas)
        hrr_W = hrr_W_m3 * V

        i_fuel = species_index_ci(gas, self.cfg.fuel_species)
        fuel_Y = float(gas.Y[i_fuel])
        fuel_mass_kg = fuel_Y * self.r.mass

        return {
            "theta_deg": math.degrees(theta_rad),
            "time_s": t_plot,
            "volume_m3": V,
            "volume_cm3": V * 1.0e6,
            "pressure_Pa": gas.P,
            "pressure_bar": p_bar,
            "temperature_K": T,
            "density_kg_m3": gas.density,
            "mass_kg": self.r.mass,
            "fuel_Y": fuel_Y,
            "fuel_mass_kg": fuel_mass_kg,
            "h_W_m2K": h,
            "wall_area_m2": A_wall,
            "Qdot_wall_W": Qdot_wall_W,
            "hrr_W_m3": hrr_W_m3,
            "hrr_W": hrr_W,
        }

    def run(self) -> Tuple[pd.DataFrame, Optional[str]]:
        rows = []
        target_times = np.linspace(0.0, self.t_end, self.cfg.num_output_points)
        stop_reason: Optional[str] = None

        print("Starte CVODE mit festen Ausgabe-Zielzeiten...")

        # Anfangszustand sofort speichern.
        rows.append(self.collect_row(0.0))

        for k, t_plot in enumerate(target_times[1:], start=1):
            try:
                self.net.advance(float(t_plot))
            except Exception as exc:
                stop_reason = f"CVODE-Abbruch bei t={t_plot:.9e} s, Index={k}: {exc}"
                print("\n[ABBRUCH] " + stop_reason)
                break

            try:
                row = self.collect_row(float(t_plot))
            except Exception as exc:
                stop_reason = f"Postprocessing-Abbruch bei t={t_plot:.9e} s, Index={k}: {exc}"
                print("\n[ABBRUCH] " + stop_reason)
                break

            rows.append(row)

            if not np.isfinite(row["temperature_K"]) or not np.isfinite(row["pressure_bar"]):
                stop_reason = f"Nicht-finites Ergebnis bei theta={row['theta_deg']:.3f} deg"
                print("\n[ABBRUCH] " + stop_reason)
                break

            if row["temperature_K"] > self.cfg.max_temperature_K:
                stop_reason = f"Temperaturlimit erreicht: {row['temperature_K']:.1f} K bei {row['theta_deg']:.2f} deg"
                print("\n[ABBRUCH] " + stop_reason)
                break

            if row["pressure_bar"] > self.cfg.max_pressure_bar:
                stop_reason = f"Drucklimit erreicht: {row['pressure_bar']:.1f} bar bei {row['theta_deg']:.2f} deg"
                print("\n[ABBRUCH] " + stop_reason)
                break

            if k % max(1, self.cfg.num_output_points // 10) == 0:
                print(
                    f"  {100.0 * k / (self.cfg.num_output_points - 1):5.1f}% | "
                    f"theta={row['theta_deg']:8.2f} deg | "
                    f"p={row['pressure_bar']:8.2f} bar | "
                    f"T={row['temperature_K']:8.1f} K"
                )

        df = pd.DataFrame(rows)
        return df, stop_reason


# -----------------------------------------------------------------------------
# Auswertung
# -----------------------------------------------------------------------------

def add_combustion_metrics(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    df = df.copy()
    t = df["time_s"].to_numpy(dtype=float)
    hrr = df["hrr_W"].to_numpy(dtype=float)
    hrr_pos = np.maximum(hrr, 0.0)

    Q_chem_J = cumulative_trapezoid(hrr_pos, t)
    df["Q_chem_J"] = Q_chem_J

    Q_total = float(np.nanmax(Q_chem_J)) if len(Q_chem_J) else 0.0
    if Q_total > 1.0e-12:
        df["mfb"] = Q_chem_J / Q_total
    else:
        df["mfb"] = 0.0

    # Druckanstiegsrate in bar/deg CA
    theta = df["theta_deg"].to_numpy(dtype=float)
    p = df["pressure_bar"].to_numpy(dtype=float)
    if len(df) >= 3:
        df["dp_dtheta_bar_per_deg"] = np.gradient(p, theta)
    else:
        df["dp_dtheta_bar_per_deg"] = 0.0

    return df


def plot_one(df: pd.DataFrame, x: str, y: str, xlabel: str, ylabel: str, title: str,
             outpath: Path, cfg: EngineConfig) -> None:
    plt.figure(figsize=(9, 5))
    plt.plot(df[x], df[y])
    plt.xlabel(xlabel)
    plt.ylabel(ylabel)
    plt.title(title)
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    if cfg.save_plots:
        plt.savefig(outpath, dpi=cfg.dpi)
    if cfg.show_plots:
        plt.show()
    plt.close()


def plot_results(df: pd.DataFrame, outdir: Path, cfg: EngineConfig) -> None:
    if df.empty:
        return

    plots = [
        ("theta_deg", "pressure_bar", "Kurbelwinkel rel. OT [deg]", "Druck [bar]", "Druck", "pressure_vs_angle.png"),
        ("theta_deg", "temperature_K", "Kurbelwinkel rel. OT [deg]", "Temperatur [K]", "Temperatur", "temperature_vs_angle.png"),
        ("volume_cm3", "pressure_bar", "Volumen [cm3]", "Druck [bar]", "p-V Diagramm", "pV_diagram.png"),
        ("theta_deg", "hrr_W", "Kurbelwinkel rel. OT [deg]", "HRR [W]", "Chemische Waermefreisetzung", "hrr_vs_angle.png"),
        ("theta_deg", "Q_chem_J", "Kurbelwinkel rel. OT [deg]", "Q_chem [J]", "Kumulierte chemische Energie", "qchem_vs_angle.png"),
        ("theta_deg", "mfb", "Kurbelwinkel rel. OT [deg]", "MFB [-]", "Mass Fraction Burned / normierter Brennverlauf", "mfb_vs_angle.png"),
        ("theta_deg", "fuel_mass_kg", "Kurbelwinkel rel. OT [deg]", "Kraftstoffmasse [kg]", "Kraftstoffabbau", "fuel_mass_vs_angle.png"),
        ("theta_deg", "dp_dtheta_bar_per_deg", "Kurbelwinkel rel. OT [deg]", "dp/dtheta [bar/deg]", "Druckanstiegsrate", "dp_dtheta_vs_angle.png"),
    ]

    for x, y, xl, yl, title, name in plots:
        if x in df.columns and y in df.columns:
            plot_one(df, x, y, xl, yl, title, outdir / name, cfg)


def write_summary(df: pd.DataFrame, outdir: Path, cfg: EngineConfig, stop_reason: Optional[str]) -> None:
    summary_path = outdir / "summary.txt"

    if df.empty:
        summary_path.write_text("Keine Daten generiert.\n", encoding="utf-8")
        return

    i_pmax = int(df["pressure_bar"].idxmax())
    i_tmax = int(df["temperature_K"].idxmax())
    i_hrrmax = int(df["hrr_W"].idxmax())

    ca10 = find_ca_from_mfb(df, 0.10)
    ca50 = find_ca_from_mfb(df, 0.50)
    ca90 = find_ca_from_mfb(df, 0.90)

    q_total = float(df["Q_chem_J"].iloc[-1]) if "Q_chem_J" in df.columns else 0.0

    lines = []
    lines.append("=== Diesel-HCCI Cantera Summary ===")
    lines.append(f"Mechanismus:          {cfg.mechanism}")
    lines.append(f"Verdichtung:          {cfg.compression_ratio:.3f}")
    lines.append(f"Drehzahl:             {cfg.rpm:.1f} 1/min")
    lines.append(f"Lambda:               {cfg.lambda_air:.3f}")
    lines.append(f"Wandtemperatur:       {cfg.wall_temperature_K:.1f} K")
    lines.append(f"Woschni-Multiplikator:{cfg.woschni_multiplier:.3f}")
    lines.append("")
    lines.append(f"Berechnete Punkte:    {len(df)}")
    if stop_reason:
        lines.append(f"Stop-Grund:           {stop_reason}")
    else:
        lines.append("Stop-Grund:           regulaer beendet")
    lines.append("")
    lines.append(f"p_max:                {df.pressure_bar.iloc[i_pmax]:.3f} bar bei {df.theta_deg.iloc[i_pmax]:.3f} deg")
    lines.append(f"T_max:                {df.temperature_K.iloc[i_tmax]:.1f} K bei {df.theta_deg.iloc[i_tmax]:.3f} deg")
    lines.append(f"HRR_max:              {df.hrr_W.iloc[i_hrrmax]:.3e} W bei {df.theta_deg.iloc[i_hrrmax]:.3f} deg")
    lines.append(f"Q_chem_total:         {q_total:.3f} J")
    lines.append(f"CA10:                 {ca10 if ca10 is not None else 'nicht erreicht'}")
    lines.append(f"CA50:                 {ca50 if ca50 is not None else 'nicht erreicht'}")
    lines.append(f"CA90:                 {ca90 if ca90 is not None else 'nicht erreicht'}")
    lines.append("")

    summary_path.write_text("\n".join(str(x) for x in lines), encoding="utf-8")

    print("\n" + "\n".join(str(x) for x in lines))
    print(f"\n[OK] Summary geschrieben: {summary_path.resolve()}")


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------

def main(cfg: EngineConfig = CFG) -> int:
    outdir = Path(cfg.output_dir)
    outdir.mkdir(parents=True, exist_ok=True)

    mech_path = Path(cfg.mechanism)
    if not mech_path.exists():
        print(f"[WARN] Mechanismus-Datei wurde nicht als direkter Pfad gefunden: {mech_path}")
        print("       Cantera versucht trotzdem, den Mechanismus ueber seinen Suchpfad zu laden.")

    gas = ct.Solution(cfg.mechanism, cfg.phase_name)

    try:
        gas.derivative_settings = {"jacobian": "analytical"}
    except Exception:
        pass

    geom = CrankSlider(cfg.bore_m, cfg.stroke_m, cfg.conrod_m, cfg.compression_ratio)
    T0, Y0, m_total, m_fuel, afr_st = build_initial_state(gas, geom, cfg)

    omega = 2.0 * math.pi * cfg.rpm / 60.0
    t_end = math.radians(cfg.theta_end_deg - cfg.theta_start_deg) / omega

    print("=== Diesel-HCCI Cantera Setup ===")
    print(f"Mechanismus:          {cfg.mechanism}")
    print(f"Spezies-Anzahl:       {gas.n_species}")
    print(f"Reaktions-Anzahl:     {gas.n_reactions}")
    print(f"Simulationsdauer:     {t_end:.6f} s")
    print(f"Verdichtung:          {cfg.compression_ratio:.3f}")
    print(f"Drehzahl:             {cfg.rpm:.1f} 1/min")
    print(f"Lambda:               {cfg.lambda_air:.3f}")
    print(f"AFR_st:               {afr_st:.3f}")
    print(f"m_total:              {m_total:.6e} kg")
    print(f"m_fuel:               {m_fuel:.6e} kg")
    print(f"T0:                   {T0:.2f} K")
    print(f"p0:                   {gas.P / 1.0e5:.3f} bar")
    print(f"Output:               {outdir.resolve()}")

    sim = CanteraEngineSimulator(gas, geom, cfg)
    df, stop_reason = sim.run()

    df = add_combustion_metrics(df)

    csv_path = outdir / "hcci_cvode_results.csv"
    df.to_csv(csv_path, index=False)
    print(f"\n[OK] CSV geschrieben: {csv_path.resolve()}")

    write_summary(df, outdir, cfg, stop_reason)

    if not df.empty:
        plot_results(df, outdir, cfg)
        if cfg.save_plots:
            print(f"[OK] Plots geschrieben nach: {outdir.resolve()}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
