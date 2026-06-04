import cantera as ct
import numpy as np
import pandas as pd
import itertools
from pathlib import Path
import sys
from multiprocessing import Pool, cpu_count

# --- 1. Globale Pfade und Parameter definieren ---
# Wichtig: Globale Definitionen, damit die Worker-Prozesse darauf zugreifen können
MECHANISM_PATH = Path(r"C:\Py_Scripte\0_MotorSim_V03\Projekte\data\NC12H26_NTC.yaml")
FUEL_SPECIES = 'NC12H26'

# --- 2. Hilfsfunktion zur Erzeugung von reinem Restgas ---
def get_burnt_gas_composition(mech, fuel):
    g = ct.Solution(mech)
    g.set_equivalence_ratio(1.0, fuel=fuel, oxidizer='O2:1.0, N2:3.76')
    g.equilibrate('HP')
    return g.X

# Vorab berechnen (wird an die Worker übergeben)
if MECHANISM_PATH.exists():
    BURNT_MOLE_FRACTIONS = get_burnt_gas_composition(str(MECHANISM_PATH), FUEL_SPECIES)
else:
    BURNT_MOLE_FRACTIONS = None

# --- 3. Die Worker-Funktion für einen einzelnen Punkt ---
def calc_single_point(args):
    """Berechnet den Zündverzug für genau eine Parameter-Kombination."""
    T, p, lam, x_egr = args
    
    phi = 1.0 / lam
    # Jeder Prozess muss sein eigenes ct.Solution-Objekt instanziieren!
    gas = ct.Solution(str(MECHANISM_PATH))
    
    # Frischgemisch einstellen
    gas.set_equivalence_ratio(phi=phi, fuel=FUEL_SPECIES, oxidizer='O2:1.0, N2:3.76')
    fresh_mass_fractions = gas.Y
    
    # Restgas holen
    gas_burnt = ct.Solution(str(MECHANISM_PATH))
    gas_burnt.X = BURNT_MOLE_FRACTIONS
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
        
    return {
        'Temperatur_K': T,
        'Druck_bar': p / 1e5,
        'Lambda': lam,
        'Phi': phi,
        'EGR_Rate': x_egr,
        'Zuendverzug_s': tau_ignition
    }

# --- 4. Hauptprogramm ---
if __name__ == '__main__':
    # Windows-spezifischer Schutz für Multiprocessing
    if not MECHANISM_PATH.exists():
        raise FileNotFoundError(f"Die Datei wurde unter {MECHANISM_PATH} nicht gefunden.")

    # Achsen definieren
    temperatures = np.linspace(700, 1100, 9)          # K
    pressures = np.linspace(30, 90, 4) * 1e5           # Pa
    lambdas = np.linspace(0.8, 5.0, 10)               # Lambda
    egr_rates = np.linspace(0.0, 0.60, 7)              # EGR

    # Alle Kombinationen generieren (Parameter-Liste für die Worker)
    param_list = list(itertools.product(temperatures, pressures, lambdas, egr_rates))
    total_iterations = len(param_list)

    num_cores = cpu_count()
    print(f"Starte PARALLELE 4D-Zündverzugsberechnung mit: {MECHANISM_PATH.name}")
    print(f"Nutze {num_cores} CPU-Kerne für {total_iterations} Punkte.")
    print("-" * 50)

    results = []
    current_iteration = 0

    # Pool von Worker-Prozessen starten
    with Pool(processes=num_cores) as pool:
        # imap_unordered ist extrem speichereffizient und liefert Ergebnisse, sobald sie fertig sind
        for res in pool.imap_unordered(calc_single_point, param_list):
            results.append(res)
            current_iteration += 1
            
            # Statusanzeige berechnen und ausgeben
            percent = (current_iteration / total_iterations) * 100
            sys.stdout.write(f"\rFortschritt: {percent:6.1f}% [{current_iteration}/{total_iterations} Punkte berechnet]")
            sys.stdout.flush()

    print("\n" + "-" * 50)

    # --- 5. Tabellenexport ---
    df = pd.DataFrame(results)
    # Da imap_unordered die Reihenfolge mischt, sortieren wir die Tabelle am Ende sauber
    df = df.sort_values(by=['Temperatur_K', 'Druck_bar', 'Lambda', 'EGR_Rate']).reset_index(drop=True)
    
    output_path = MECHANISM_PATH.parent / 'diesel_ntc_zuendverzug_4d.csv'
    df.to_csv(output_path, index=False)

    print(f"Berechnung erfolgreich beendet! Tabelle gespeichert in:\n{output_path}")