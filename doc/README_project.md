# Thermo0D / MotorSim V03

Stand: 2026-05-12

Diese README fasst den aktuellen Projektstand und die Aenderungen zusammen, die in der Codex-Bearbeitung dokumentiert bzw. nachgezogen wurden. Der Ordner ist aktuell kein Git-Repository; die Zusammenfassung basiert deshalb auf den vorhandenen Patch-Notizen, README-Zwischenstaenden und der Projektstruktur.

## Kurzueberblick

Thermo0D / MotorSim ist ein datengetriebenes 0D-Kreisprozess-Framework fuer klassische Kurbeltrieb-Motoren und Free-Piston-Faelle. Der aktuelle Stand trennt Konfiguration, Modellaufbau, Rechenkern, Physik, Ausgabe und GUI-Werkzeuge klarer voneinander.

Wichtige Projektbereiche:

- `src/thermo0d/` - Quellcode
- `scripts/` - Start- und Hilfsskripte
- `tests/` - automatisierte Tests
- `Projekte/` - Projektdateien, Varianten, Plot-Layouts und Ergebnisse
- `doc/` - technische Dokumentation und Patch-Dokumentation

## In Codex nachgezogene Aenderungen

### 1. Bereinigter Projektstand

- Projektstruktur auf die wesentlichen Ordner konsolidiert.
- Dokumentierte Varianten und Beispielkonfigurationen liegen bevorzugt unter `Projekte/variants/`.
- Alte Zwischenstaende, Caches, Backup-Kopien und temporare Ergebnisordner wurden in den README-Notizen als zu bereinigende Artefakte markiert.
- Die zentrale `README.md` dient jetzt als Einstieg in den aktuellen Stand.

### 2. Free-Piston-Modellpfad

Der Free-Piston-Pfad wurde als eigener Modellzweig weitergefuehrt. Die Bewegung wird ueber translatorische Zustaende beschrieben, nicht ueber klassische Kurbelkinematik.

Wichtige Konzepte:

- `modeling.architecture: free_piston`
- `free_piston.initial_conditions.*`
- `free_piston.mechanics.*`
- `free_piston.friction.*`
- `free_piston.load.*`
- `free_piston.bounce.*`
- Topologie weiterhin unter `preprocessing.volumes` und `preprocessing.connections`

Die Kolbenlage wird ueber `x_min_m` und `x_max_m` beschrieben:

- `x_min_m` entspricht BDC/UT
- `x_max_m` entspricht TDC/OT
- Hub = `x_max_m - x_min_m`
- Abstand von TDC = `x_max_m - x`

Slots mit `opening_mode: by_distance` werden relativ zu diesem TDC-Abstand ausgewertet.

### 3. Massenmodell Phase 1

Der Zustandsraum pro Volumen wurde fuer ein saubereres Massenmodell erweitert:

- `m_gas`
- `U`
- `m_burned`
- `m_air`
- `m_fuel_liquid`

Abgeleitete Groessen:

- `m_fuel_vapor = m_gas - m_air - m_burned`
- `m_fuel_total = m_fuel_vapor + m_fuel_liquid`

Damit koennen frische Luft, Kraftstoffdampf, fluessiger Kraftstoff und verbranntes Gas getrennt transportiert bzw. rekonstruiert werden.

### 4. Reduziertes Mischungs-Stoffwertmodell Phase 2

Das bisherige vereinfachte Stoffwertmodell wurde fuer `R`, `cp`, `cv` und `kappa` auf ein reduziertes Dreikomponentenmodell umgestellt:

- frische Luft
- Kraftstoffdampf
- verbranntes Gas

Die Diagnosegroesse `lambda` bleibt erhalten, wird aber aus `m_air` und `m_fuel_vapor` gebildet. Der Free-Piston-Thermopfad nutzt damit nicht mehr nur Gesamtmasse und Gesamt-Fuel-Anteil, sondern die expliziten Massenkomponenten.

### 5. Burned-/Unburned-Erweiterung

Fuer Free-Piston-Startbedingungen gibt es unter `free_piston.initial_conditions.combustion_state` zusaetzlich:

- `burned_mass_percent` in Prozent
- weiterhin kompatibel: `burned_fraction_0to1`

Wirkung:

- Der Builder setzt die anfaengliche verbrannte Zylindermasse real aus dem konfigurierten Startanteil.
- Der automatische Restart-Update kann `burned_fraction_0to1` und `burned_mass_percent` in die YAML zurueckschreiben.
- Generierte Ergebnis-READMEs koennen `restgas_anteil_brennbeginn_percent` ausgeben.
- Last-Cycle-Tabellen enthalten zusaetzliche `combustion_start_*`-Groessen, wenn ein Brennbeginn erkannt wurde.

Neue rekonstruierte Verbindungssignale:

- `<connection>_mdot_kg_per_s`
- `<connection>_mdot_unburned_kg_per_s`
- `<connection>_mdot_burned_kg_per_s`

### 6. Thermodynamik-Modellschalter

Es wurde ein konfigurierbarer Schalter fuer das Thermomodell dokumentiert:

```yaml
preprocessing:
  gas_properties:
    cp_J_per_kgK: 1005.0
    cv_J_per_kgK: 718.0
    R_J_per_kgK: 287.0
    thermo_model: constant      # constant | quellen_step1
```

Hinweis aus den Patch-Notizen: `released_energy_J`, `ignition_armed` und `injection_armed` sind Metadaten bzw. Bookkeeping-Felder und nicht der Thermomodell-Schalter.

### 7. Lokale Energieterme und Source Terms

Die lokalen Energieterme wurden in eigene Physikmodule bzw. gemeinsame Auswertelogik ausgelagert. Ziel ist, dass Solver, Export und Plot-Auswertung dieselben Quellterm-Definitionen verwenden.

Betroffene Themen:

- Wandwaerme
- Vibe-Verbrennung
- Evaporation
- `p*dV`
- gemeinsame Source-Term-Auswertung

Dadurch reduziert sich doppelte Physiklogik zwischen RHS, Export und Plot-Auswertung.

### 8. Winkelreferenzen und zyklische Fenster

Die `angle_reference`-Logik wurde bereinigt:

- `absolute` nutzt den globalen Kurbelwinkel.
- `compression_tdc` und `gas_exchange_tdc` nutzen den lokalen zylinderbezogenen Winkel.

Verbrennungs- und Evaporationsfenster duerfen ueber den Zyklusursprung laufen, z. B. `start_deg = 350`, `duration_deg = 30`.

### 9. Plot- und Frame-Export

Der Plotpfad wurde fuer Free-Piston-Auswertungen erweitert.

Dokumentierte Funktionen:

- Free-Piston-Plotlayouts fuer Druck, Masse, Energie, Kraefte, Slot-Hoehen und Massenstrom-Komponenten
- UT-OT-UT-Auswertung fuer den letzten vollstaendigen Hub
- optionaler Frame-Export fuer Stroke-Animationen
- Beispielskript: `examples_stroke_export.py`
- Quickstart: `STROKE_FRAME_EXPORT_QUICKSTART.md`

Typische Plot-Dateien:

- `Projekte/variants/plot_fp.yaml`
- `Projekte/variants/plot-fp_pressure.yaml`
- `Projekte/variants/plot-fp_mass.yaml`
- `Projekte/variants/plot-fp_transfer_slot_mass_components.yaml`
- `Projekte/variants/plot-fp_exhaust_slot_mass_components.yaml`

### 10. GUI- und Tooling-Verbesserungen

Aus den dokumentierten Zwischenstaenden wurden folgende Werkzeug-Themen nachgezogen:

- robuster Plot-Editor mit Y-Limits, Grid-Einstellungen, Signalfilter und Subplot-DnD
- Alias-Editor mit Fehlerdialogen und exakten Dateipfaden
- Topology-Editor mit Schema-Metadaten und Rueckwaertskompatibilitaet
- `scripts/config_tool.py` fuer `validate`, `upgrade`, `normalize`, `explain` und `diff`
- Checkreport als CSV, Konsolenreport und optional HTML

## Wichtige geaenderte bzw. betroffene Dateien

Aus den Patch-Notizen ergeben sich besonders diese Bereiche:

- `src/thermo0d/core/state_layout.py`
- `src/thermo0d/config/models.py`
- `src/thermo0d/config/restart_state_update.py`
- `src/thermo0d/compute/analysis.py`
- `src/thermo0d/compute/jacobian.py`
- `src/thermo0d/physics/rhs.py`
- `src/thermo0d/physics/quellen_props.py`
- `src/thermo0d/model/conventional/builder.py`
- `src/thermo0d/model/free_piston/builder.py`
- `src/thermo0d/model/free_piston/rhs.py`
- `src/thermo0d/model/free_piston/postprocessing.py`
- `src/thermo0d/output/reconstruction.py`
- `src/thermo0d/output/geometry_report.py`
- `src/thermo0d/output/plots.py`
- `src/thermo0d/output/plot_layout.py`

## Startbefehle

Klassische Simulation:

```bash
python scripts/run_simulation.py --config Projekte/variants/config_1cyl_4t.yaml
```

Free-Piston-Fall:

```bash
python scripts/run_simulation.py --config Projekte/variants/free_piston_coldflow.yaml
```

Plot-Editor:

```bash
python scripts/run_plot_editor.py
```

Gaswechsel-Editor:

```bash
python scripts/run_gasexchange_editor.py
```

Topologie-Editor:

```bash
python scripts/run_topology_config_editor.py
```

Config-Tool:

```bash
python scripts/config_tool.py validate Projekte/variants/free_piston_coldflow.yaml
```

Stroke-Frame-Beispiel:

```bash
python examples_stroke_export.py --mode fast
```

## Verifikation laut Patch-Notizen

In den vorhandenen Notizen wurden unter anderem folgende Checks dokumentiert:

- `python -m compileall src/thermo0d`
- Smoke-Test mit `Projekte/variants/free_piston_GenSet_V09f.yaml`
- Aufbau eines Free-Piston-Bundles
- `compute_free_piston_rhs(0.0, y_init, bundle)` liefert endliche Werte
- Tests fuer Coldflow- und Stroke-Frame-Export-Pfade

## Bekannte Hinweise

- Dieser Ordner ist aktuell kein Git-Repository; ein exakter Git-Diff war daher nicht verfuegbar.
- Einige alte README- und Patch-Dateien bleiben als Verlauf/Arbeitsnotizen im Projekt liegen.
- In einer Patch-Notiz wurde ein auffaelliger Wert in `Projekte/variants/free_piston_GenSet_V09d.yaml` dokumentiert: `bounce.initial_temperature_K` war dort mit einem physikalisch unplausiblen Wert angegeben und sollte vor weiterer Fehlersuche auf einen realistischen Wert, z. B. `300.0 K`, gesetzt werden.
- Generierte Ergebnisordner und Caches sollten vor Archivierung separat bereinigt werden.

## Weiterfuehrende Dokumentation

- `README_updated.md`
- `README_plot.md`
- `STROKE_FRAME_EXPORT_QUICKSTART.md`
- `PHASE1_PHASE2_COMBINED_NOTES.md`
- `PATCH_NOTES_burned_unburned_v2.md`
- `FREE_PISTON_THERMO_COMPONENTS_NOTES.md`
- `THERMO_MODEL_TOGGLE_PATCH_NOTES.txt`
- `doc/patch-doc/`
