import cantera as ct
import numpy as np
import pandas as pd
import itertools
from pathlib import Path
import sys

# --- 1. Pfade und Parameterbereiche definieren ---
mechanism_path = Path(r"C:\Py_Scripte\0_MotorSim_V03\Projekte\data\NC12H26_NTC.yaml")
fuel_species = 'NC12H26'

if not mechanism_path.exists():
    raise FileNotFoundError(f"Die Datei wurde unter {mechanism_path} nicht gefunden.")

mechanism = str(mechanism_path)

temperatures = np.linspace(700, 2500, 15)          # K
pressures = np.linspace(30, 120, 20) * 1e5           # Pa
lambdas = np.linspace(0.8, 5.0, 10)               # Lambda
egr_rates = np.linspace(0.0, 0.60, 7)              # EGR

# --- Gesamtzahl der Schleifendurchläufe berechnen ---
total_iterations = len(temperatures) * len(pressures) * len(lambdas) * len(egr_rates)

results = []
print(f"Starte 4D-Zündverzugsberechnung mit: {mechanism_path.name}")
print(f"Gesamtanzahl zu berechnender Punkte: {total_iterations}")
print("-" * 50)

# --- 2. Hilfsfunktion zur Erzeugung von reinem Restgas ---
def get_burnt_gas_composition(mech, fuel):
    g = ct.Solution(mech)
    g.set_equivalence_ratio(1.0, fuel=fuel, oxidizer='O2:1.0, N2:3.76')
    g.equilibrate('HP')
    return g.X

burnt_mole_fractions = get_burnt_gas_composition(mechanism, fuel_species)

# --- 3. Simulations-Schleife (4D) mit Statusanzeige ---
current_iteration = 0

for T, p, lam, x_egr in itertools.product(temperatures, pressures, lambdas, egr_rates):
    
    current_iteration += 1
    
    # Fortschritt in Prozent berechnen
    percent = (current_iteration / total_iterations) * 100
    # Statuszeile im Terminal überschreiben (\r sorgt für den Carriage Return)
    sys.stdout.write(f"\rFortschritt: {percent:6.1f}% [{current_iteration}/{total_iterations} Punkte berechnet]")
    sys.stdout.flush()
    
    phi = 1.0 / lam
    gas = ct.Solution(mechanism)
    
    # Frischgemisch einstellen
    gas.set_equivalence_ratio(phi=phi, fuel=fuel_species, oxidizer='O2:1.0, N2:3.76')
    fresh_mass_fractions = gas.Y
    
    # Restgas holen
    gas_burnt = ct.Solution(mechanism)
    gas_burnt.X = burnt_mole_fractions
    burnt_mass_fractions = gas_burnt.Y
    
    # Mischen
    mixed_mass_fractions = (1.0 - x_egr) * fresh_mass_fractions + x_egr * burnt_mass_fractions
    
    gas.Y = mixed_mass_fractions
    gas.TP = T, p
    
    r = ct.IdealGasReactor(gas)
    sim = ct.ReactorNet([r])
    
    time = 0.0
    times = []
    temps = []
    
    while time < 0.20: 
        time = sim.step()
        times.append(time)
        temps.append(r.T)
        
        if r.T > T + 400:
            break
            
    if len(temps) > 1 and (temps[-1] > T + 400):
        dt = np.diff(times)
        dT = np.diff(temps)
        dT_dt = np.where(dt > 0, dT / dt, 0)
        tau_ignition = times[np.argmax(dT_dt)]
    else:
        tau_ignition = np.nan
        
    results.append({
        'Temperatur_K': T,
        'Druck_bar': p / 1e5,
        'Lambda': lam,
        'Phi': phi,
        'EGR_Rate': x_egr,
        'Zuendverzug_s': tau_ignition
    })

# Zeilenumbruch nach Abschluss der Schleife, damit nachfolgende Prints sauber starten
print("\n" + "-" * 50)

# --- 4. Tabellenexport ---
df = pd.DataFrame(results)
output_path = mechanism_path.parent / 'diesel_ntc_zuendverzug_4d.csv'
df.to_csv(output_path, index=False)

print(f"Berechnung erfolgreich beendet! Tabelle gespeichert in:\n{output_path}")