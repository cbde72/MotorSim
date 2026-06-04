import numpy as np
import pandas as pd
from pathlib import Path

def convert_motorsim_npz_to_csv(npz_path: str | Path):
    npz_file = Path(npz_path)
    if not npz_file.exists():
        raise FileNotFoundError(f"Datei nicht gefunden: {npz_file}")
        
    print(f"Lade Simulationsdaten aus: {npz_file.name}")
    
    # Daten aus der NPZ extrahieren
    with np.load(npz_file, allow_pickle=True) as data:
        t_s = data['t_s']              # Zeitachse (Shape: 20001,)
        y = data['y']                  # Werte-Matrix (Shape: 62, 20001)
        state_names = data['state_names']  # Namen (Shape: 62,)
        state_units = data['state_units']  # Einheiten (Shape: 62,)
        
    print("Strukturiere Matrix und füge Header zusammen...")
    
    # 1. Schritt: Die Werte-Matrix y transponieren von (62, 20001) auf (20001, 62)
    # Dadurch wird jeder Zustand zu einer Spalte und die Zeitschritte laufen nach unten
    y_transposed = y.T
    
    # Spaltennamen für Pandas vorbereiten (Zeit-Spalte + die 62 Zustände)
    columns = ['time_s'] + list(state_names)
    
    # 2. Schritt: Haupt-Daten-DataFrame erstellen
    # Wir fügen t_s als erste Spalte links an die transponierten Werte an
    data_matrix = np.column_stack((t_s, y_transposed))
    df_values = pd.DataFrame(data_matrix, columns=columns)
    
    # 3. Schritt: Die Einheiten-Zeile vorbereiten
    # Erste Spalte ist 's' für die Zeit, danach folgen die Einheiten der Zustände
    units_row = ['s'] + list(state_units)
    df_units = pd.DataFrame([units_row], columns=columns)
    
    # 4. Schritt: Einheiten-Zeile und Werte-Tabelle untereinander hängen
    # Zeile 0 im CSV wird der Spaltenname sein (automatisch durch Pandas)
    # Zeile 1 wird die Einheit sein
    # Ab Zeile 2 folgen die Werte
    df_final = pd.concat([df_units, df_values], ignore_index=True)
    
    # Speicherpfad definieren (dieselbe Datei, nur mit .csv Endung)
    output_csv = npz_file.with_suffix('.csv')
    
    print(f"Schreibe spaltenweise CSV (Zeilen: {df_final.shape[0]}, Spalten: {df_final.shape[1]})...")
    
    # Export mit Semikolon als Trennzeichen, ohne den Pandas-Index
    df_final.to_csv(output_csv, sep=';', index=False)
    
    print(f"Erfolgreich konvertiert! Datei gespeichert unter:\n{output_csv}")

if __name__ == '__main__':
    # Pfad zu deiner hochgeladenen run_raw.npz
    #npz_pfad = r"C:\Py_Scripte\0_MotorSim_V03\Projekte\variants\results\run_raw.npz" 
    npz_pfad = r"Projekte/variants/results/free_piston_GenSet_V22/raw/run_raw.npz"

    # (Passe den Ordnerpfad an, falls sich der Speicherort unterscheidet)
    
    try:
        convert_motorsim_npz_to_csv(npz_pfad)
    except Exception as e:
        print(f"Fehler bei der Konvertierung: {e}")