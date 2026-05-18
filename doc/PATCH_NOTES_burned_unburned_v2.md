# Patch Notes – burned/unburned Erweiterung v2

## Neu in diesem Patch

### 1) Initialer Restgas-/Burned-Anteil bei `x0_m`
Für `free_piston.initial_conditions.combustion_state` gibt es jetzt zusätzlich:

- `burned_mass_percent` in `%` (0..100)

Weiterhin bleibt `burned_fraction_0to1` nutzbar.

Wirkung:
- Der Builder setzt die anfängliche verbrannte Zylindermasse `m_burned` jetzt real aus dem konfigurierten Startanteil.
- Das gilt auch dann, wenn `postprocessing.auto_update_initial_conditions: false` gesetzt ist.

### 2) Auto-Update der Startwerte
Wenn `auto_update_initial_conditions: true` aktiv ist, schreibt der automatische Restart-Update jetzt zusätzlich in die YAML:

- `free_piston.initial_conditions.combustion_state.burned_fraction_0to1`
- `free_piston.initial_conditions.combustion_state.burned_mass_percent`

Damit wird der am letzten Kompressionshub bei `x0_m` vorhandene Restgasanteil mitgeführt.

### 3) README / Last-Cycle
In der generierten `README.md` wird jetzt zusätzlich ausgegeben:

- `restgas_anteil_brennbeginn_percent`

Ermittlung:
- aus dem ersten Brennbeginn-Sample des letzten vollständigen UT→OT→UT-Zyklus
- berechnet als:
  - `m_burned / m_total * 100`

Außerdem werden jetzt auch `combustion_start_*` Zustandsgrößen in die Last-Cycle-Tabelle aufgenommen, wenn Brennbeginn erkannt wurde.

### 4) Neue Verbindungssignale für Massenstrom-Komponenten
Für alle Verbindungen werden jetzt zusätzlich rekonstruiert:

- `<connection>_mdot_kg_per_s`
- `<connection>_mdot_unburned_kg_per_s`
- `<connection>_mdot_burned_kg_per_s`

Die Vorzeichenrichtung bleibt identisch zur bisherigen Gesamt-Massenstromdefinition.

### 5) Neue Plot-Dateien
Neu erzeugt:

- `plot-fp_transfer_slot_mass_components.yaml`
- `plot-fp_exhaust_slot_mass_components.yaml`

Beide im Stil der vorhandenen `plot-fp_temperature.yaml`.

## Geänderte Dateien

- `src/thermo0d/config/models.py`
- `src/thermo0d/model/free_piston/builder.py`
- `src/thermo0d/config/restart_state_update.py`
- `src/thermo0d/output/reconstruction.py`
- `src/thermo0d/output/geometry_report.py`
- `README.md`
- `Projekte/variants/free_piston_Vibe_V04.yaml`
- `Projekte/variants/free_piston_GenSet_V09d.yaml`
- `Projekte/variants/plot-fp_transfer_slot_mass_components.yaml`
- `Projekte/variants/plot-fp_exhaust_slot_mass_components.yaml`
