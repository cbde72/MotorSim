#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1D-Segment-Modellierung eines kurzen Abgasrohrs (30 cm) zur Berechnung von 
Reynolds, Prandtl, Filonenko-Reibungsbeiwert, Gnielinski-Nusselt und alpha.
"""

from __future__ import annotations
import math
from dataclasses import dataclass
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

@dataclass
class PipeConfig:
    # Geometrie
    diameter_m: float = 0.030         # 30 mm Innendurchmesser
    length_m: float = 0.30            # 30 cm Gesamtlänge
    segments: int = 30                # Diskretisierung (1 cm pro Segment)
    
    # Randbedingungen Gas
    T_in_C: float = 600.0             # 600 °C Eintrittstemperatur
    m_dot_kgh: float = 400.0          # 400 kg/h Massenstrom
    
    # Randbedingungen Wand
    T_wall_C: float = 20.0            # Konstante Wandtemperatur

class GasPropertiesAir:
    """Modellierung der Stoffwerte für Luft/Abgas bei 1 bar."""
    @staticmethod
    def density(T_C: float) -> float:
        return 100000.0 / (287.0 * (T_C + 273.15))

    @staticmethod
    def dynamic_viscosity(T_C: float) -> float:
        T = T_C + 273.15
        return 1.458e-6 * (T**1.5) / (T + 110.4)

    @staticmethod
    def thermal_conductivity(T_C: float) -> float:
        T = T_C + 273.15
        return 2.334e-3 * (T**0.75)

    @staticmethod
    def cp(T_C: float) -> float:
        T = T_C + 273.15
        return 1000.0 + 0.15 * (T - 273.15)

def calculate_short_pipe(cfg: PipeConfig) -> pd.DataFrame:
    m_dot = cfg.m_dot_kgh / 3600.0    # kg/s
    dx = cfg.length_m / cfg.segments   # 0.01 m pro Segment
    A_cross = math.pi * (cfg.diameter_m**2) / 4.0
    A_wall_seg = math.pi * cfg.diameter_m * dx
    
    T_current = cfg.T_in_C
    x_current = 0.0
    
    rows = []
    
    for seg in range(cfg.segments):
        rho = GasPropertiesAir.density(T_current)
        eta = GasPropertiesAir.dynamic_viscosity(T_current)
        lambda_g = GasPropertiesAir.thermal_conductivity(T_current)
        cp = GasPropertiesAir.cp(T_current)
        
        w = m_dot / (rho * A_cross)
        Re = (rho * w * cfg.diameter_m) / eta
        Pr = (eta * cp) / lambda_g
        
        # Turbulenter Wärmeübergang nach Filonenko & Gnielinski
        if Re > 2300:
            zeta = (1.82 * math.log10(Re) - 1.64)**(-2)
            num = (zeta / 8.0) * (Re - 1000.0) * Pr
            den = 1.0 + 12.7 * math.sqrt(zeta / 8.0) * (Pr**(2.0/3.0) - 1.0)
            Nu = num / den
        else:
            zeta = 64.0 / Re
            Nu = 3.66
            
        alpha = Nu * (lambda_g / cfg.diameter_m)
        
        # Enthalpiebasierte Abkühlung
        Q_dot_seg = alpha * A_wall_seg * (T_current - cfg.T_wall_C)
        dT = Q_dot_seg / (m_dot * cp)
        
        rows.append({
            "x_cm": (x_current + dx/2.0) * 100.0,
            "T_gas_C": T_current,
            "velocity_m_s": w,
            "Re": Re,
            "Pr": Pr,
            "zeta": zeta,
            "Nu": Nu,
            "alpha_W_m2K": alpha,
            "Q_dot_seg_W": Q_dot_seg
        })
        
        T_current -= dT
        x_current += dx
        
    return pd.DataFrame(rows)

def plot_results(df: pd.DataFrame):
    fig, ax1 = plt.subplots(figsize=(9, 5))
    
    color = 'crimson'
    ax1.set_xlabel('Rohrlänge [cm]')
    ax1.set_ylabel('Abgastemperatur [°C]', color=color)
    ax1.plot(df['x_cm'], df['T_gas_C'], color=color, linewidth=2.5)
    ax1.tick_params(axis='y', labelcolor=color)
    ax1.grid(True, alpha=0.3)
    
    ax2 = ax1.twinx()
    color = 'royalblue'
    ax2.set_ylabel('alpha [W/m²K]', color=color)
    ax2.plot(df['x_cm'], df['alpha_W_m2K'], color=color, linestyle='--', linewidth=2)
    ax2.tick_params(axis='y', labelcolor=color)
    
    fig.tight_layout()
    plt.title('Wärmeübergang und Gastemperatur über 30 cm Rohrlänge')
    plt.show()

if __name__ == "__main__":
    cfg = PipeConfig()
    df_results = calculate_short_pipe(cfg)
    
    print("=== Ergebnisse für das 30 cm kurze Abgasrohr ===")
    print(f"Eintrittstemperatur: {df_results['T_gas_C'].iloc[0]:.2f} °C")
    print(f"Austrittstemperatur: {df_results['T_gas_C'].iloc[-1]:.2f} °C")
    print(f"Temperaturdifferenz: {df_results['T_gas_C'].iloc[0] - df_results['T_gas_C'].iloc[-1]:.3f} K")
    print(f"Wärmeübergang (alpha): {df_results['alpha_W_m2K'].mean():.1f} W/m²K")
    print(f"Reynolds-Zahl:        {df_results['Re'].mean():.0f}")
    print(f"Strömungsgeschw.:     {df_results['velocity_m_s'].mean():.1f} m/s")
    print(f"Gesamter Wärmeverlust: {df_results['Q_dot_seg_W'].sum():.1f} W")
    
    plot_results(df_results)