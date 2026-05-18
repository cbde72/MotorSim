# Quellen-Archiv Schritt 1

Umgesetzt ist ein erster Stoffwert-Zwischenschritt im Stil des Quellen-Archivs:

- neue Stoffwertkorrelation `src/thermo0d/physics/quellen_props.py`
- `R(lambda)`, `cv(lambda,T)`, `cp=cv+R`, `gamma=cp/cv`
- Temperatur aus `m,U,lambda` iterativ wie im Quellen-Ansatz
- variable Stoffwerte im klassischen RHS und im Free-Piston-RHS
- Upstream-`gamma`, `R`, `cp` für Massestrom und Enthalpiestrom
- Builder speichern je Volumen optionale Brennstoffmasse und stöchiometrisches AFR
- initiale innere Energie wird mit dem neuen `cv(lambda,T)` neu gesetzt
- Rekonstruktion/Postprocessing geben zusätzliche Stoffwertsignale aus

## Wichtige Einschränkungen

- `lambda` wird nur dort physikalisch sinnvoll, wo echte `fuel_mass_per_cycle_kg` oder beim Free-Piston eine gelatchte Brennstoffmasse vorliegt.
- Konfigurationen mit nur `added_energy_per_cycle_J` ohne echte Brennstoffmasse fallen auf ein luftähnliches Verhalten zurück.
- Das ist bewusst ein Zwischenschritt vor einem echten zusammensetzungsbasierten Modell.

## Geänderte Dateien

- `src/thermo0d/physics/quellen_props.py`
- `src/thermo0d/physics/rhs.py`
- `src/thermo0d/model/free_piston/rhs.py`
- `src/thermo0d/model/conventional/builder.py`
- `src/thermo0d/model/free_piston/builder.py`
- `src/thermo0d/core/model_bundle.py`
- `src/thermo0d/output/reconstruction.py`
- `src/thermo0d/model/free_piston/postprocessing.py`
