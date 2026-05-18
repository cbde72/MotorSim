# thermo0d v0.4

## Konsolidierter Stand vom 01.04.2026

Dieses Archiv enthält den konsolidierten Gesamtstand eines datengetriebenen 0D-Kreisprozess-Frameworks mit klarer Trennung von Eingabe, Rechenkern, Ausgabe und GUI-Werkzeugen.

Der aktuelle Stand enthält zusätzlich die zuletzt nachgezogenen Physik- und Auswerte-Hotfixes für:
- zentrale Auslagerung lokaler Energieterme aus `rhs.py`
- saubere Trennung von Wandwärme, Verbrennung und Evaporation in eigene Physik-Module
- korrigierte `angle_reference`-Logik für `absolute`, `compression_tdc` und `gas_exchange_tdc`
- Wrap-Logik für zyklusübergreifende Fenster von Verbrennung und Evaporation
- konsistente Nutzung derselben Source-Term-Logik in Solver, Export und Plot-Auswertung

Enthalten sind außerdem die bereits zuvor nachgezogenen Konsolidierungs-Hotfixes:
- Topology-Editor: fehlende `schema_meta`-Imports behoben (`meta_for`, `SOLVER_KINDS`, `SAMPLING_MODES`, `ANGLE_REFERENCES`, `PROFILE_ANGLE_DOMAINS`)
- Topology-Editor: deaktivierte Teilmodelle werden beim Speichern bereinigt und rückwärtskompatibel geladen
- Matrix-Builder: `combustion.model: none` und `evaporation.model: none` werden robust verarbeitet
- Topologie: `environment`-Volumina mit festen Zuständen `pressure_Pa` / `temperature_K` und `orifice`-Verbindungen als Drosselpfad
- Loader/GUI: robuste mm→m-Erkennung für `alpha_k_file`
- Wandwärme: einheitlicher Woschni-Pfad für Solver und Export

## Wesentliche Änderungen dieses Stands

- `run_simulation.py` mit auswählbaren `simulated_args`-Presets, `project_A156A1` als Default
- Konfigurations-Versionierung mit echter Schema-Migration und Rückwärtskompatibilität
- formatierte Pydantic-, YAML- und Dateifehler in Loader und CLI
- projektweite Vordergrund-Dialoge über `src/thermo0d/gui/dialogs.py`
- robuster Alias-Editor mit Fehlerdialogen, exakten Dateipfaden und optionalem Start ohne Auto-Generierung
- PlotStyleEditor mit Y-Limits, Y-Min/Y-Max, Major/Minor-Step, Major/Minor-Grid, stabiler Inspector-Auswahl, echter Treffer-Markierung im Signalfilter und Subplot-DnD zwischen Figures
- ergonomische Plot-Editor-Erweiterungen: Achsenstil kopieren/einfügen, auf Subplot oder alle Subplots anwenden, intelligente Auto-Limits aus Preview-Daten
- Startbedingungen bevorzugt über `initial_pressure_Pa` und `initial_temperature_K`, `initial_mass_kg` nur als Fallback
- Config-Kern weiter bereinigt: zusätzliche Bereichsprüfungen, schema-sichere Normalisierung und Master-Referenz-Config
- neues `scripts/config_tool.py` für `validate`, `upgrade`, `normalize`, `explain` und `diff`
- automatischer Last-Cycle-Checkreport als CSV, Konsolenreport und optional HTML
- fallklassenabhängige Ampelbewertung des Checkreports für geschlossene Fälle, Coldflow-Gaswechsel sowie gezündete 2T/4T-Fälle
- bereinigtes Archiv inkl. `doc/index.html`, `doc/app.js`, `doc/data.js` und `Projekte/data/`
- Hotfix für konsolidierte Pakete: `migrate_config_data(...)` und `migrate_yaml_text(...)` werden wieder exportiert

## Neu im Physikkern dieses Stands

### 1. Lokale Energieterme aus `rhs.py` ausgelagert

Die bisher in `src/thermo0d/physics/rhs.py` eingebetteten Modelle für Verbrennung und Evaporation wurden in eigene Module ausgelagert:

- `src/thermo0d/physics/heat_transfer.py`
- `src/thermo0d/physics/combustion.py`
- `src/thermo0d/physics/evaporation.py`
- `src/thermo0d/physics/source_terms.py`

Damit übernimmt `rhs.py` wieder primär die Bilanzgleichungen und die Zusammenführung der einzelnen Beiträge.

### 2. Gemeinsame Source-Term-Auswertung

`src/thermo0d/physics/source_terms.py` bündelt die lokalen Energieterme je Zylindervolumen:

- `p*dV`
- Wandwärme
- Vibe-Verbrennung
- Evaporations-Sinkterm

Diese Auswertung wird jetzt konsistent in folgenden Pfaden genutzt:
- Solver / `rhs.py`
- Export / `output/rows.py`
- Plot-Auswertung / `output/plots.py`

Dadurch werden doppelte Physikimplementierungen reduziert und Export-/Plotwerte folgen derselben Logik wie die eigentliche RHS.

### 3. `angle_reference` korrigiert

Die Winkelreferenzierung wurde fachlich bereinigt:

- `absolute` verwendet jetzt den **globalen Kurbelwinkel** ohne Zylinder-Phasenverschiebung
- `compression_tdc` und `gas_exchange_tdc` verwenden weiterhin den **lokalen zylinderbezogenen Winkel**

Dadurch sind phase-shifted Zylinder bei Ereignissen, Profilen und Energietermen korrekt referenziert.

### 4. Wrap-Logik für zyklusübergreifende Fenster

Verbrennungs- und Evaporationsfenster dürfen jetzt über den Zyklusursprung laufen, zum Beispiel:
- `start_deg = 350`, `duration_deg = 30` in 2T
- `start_deg = 710`, `duration_deg = 40` in 4T

Die Aktivierung und Fortschrittsberechnung dieser Fenster wird jetzt korrekt zyklisch ausgewertet.

### 5. Plot-/GUI-Seite nachgezogen

Die Winkel- und Ereignislogik wurde für die Darstellungsseite mitgezogen:
- `src/thermo0d/output/plot_layout.py`
- `src/thermo0d/gui/plot_style_editor.py`

Damit bleiben Eventmarker, Layout-Auswertung und Solver-Referenzierung konsistent.

## Architektur

Die Codebasis trennt strikt zwischen:
- **Input**: Laden, Validieren, Auflösen von Pfaden, Aufbau kompakter Simulationsdaten
- **Compute**: Solver, Integrationslauf, Kennwerte
- **Physics**: Kinematik, Strömung, lokale Quell- und Senkterme
- **Output**: Sampling, Zeilenaufbau, CSV-/Excel-Export, Konsolenreporting
- **App/GUI**: Orchestrierung, Editoren, Werkzeuge

Der physikalische Rechenkern ist damit von YAML-Dateien, Exportformaten und GUI-Code getrennt.

## Paketstruktur

```text
src/thermo0d/
├─ app/
├─ compute/
├─ config/
├─ core/
├─ gui/
├─ input/
├─ output/
├─ physics/
├─ config_versioning.py
├─ main.py
└─ version.py
```

## Wichtige Komponenten

### Input
- `thermo0d.input.config_loader.ConfigLoader`
- `thermo0d.input.config_resolver.ConfigResolver`
- `thermo0d.input.model_builder.MatrixModelBuilder`

### Compute
- `thermo0d.compute.solvers.SolverFactory`
- `thermo0d.compute.executor.SimulationExecutor`
- `thermo0d.compute.analysis.CycleSummaryCalculator`

### Physics
- `thermo0d.physics.kinematics`
- `thermo0d.physics.flow`
- `thermo0d.physics.heat_transfer`
- `thermo0d.physics.combustion`
- `thermo0d.physics.evaporation`
- `thermo0d.physics.source_terms`
- `thermo0d.physics.rhs`

### Output
- `thermo0d.output.sampling.OutputSampler`
- `thermo0d.output.rows.ResultRowBuilder`
- `thermo0d.output.exporters.CsvExporter` / `ExcelExporter`
- `thermo0d.output.console.ConsoleCycleReporter`
- `thermo0d.output.service.PostprocessingService`

## Physikmodell: aktueller funktionaler Umfang

### Wandwärme
Die Wandwärme wird zentral über `src/thermo0d/physics/heat_transfer.py` ausgewertet. Der aktuelle Pfad nutzt eine vereinfachte Woschni-artige HTC-Korrelation, die in Solver und Export konsistent verwendet wird.

### Verbrennung
`src/thermo0d/physics/combustion.py` implementiert aktuell eine vorgegebene Vibe-Wärmefreisetzung als Energieterm pro Zyklusfenster.

Wichtig:
- derzeit **keine** Speziesbilanz
- derzeit **keine** O₂-Verbrauchsrechnung
- derzeit **keine** Kopplung an eine separate flüssige Kraftstoffmasse

### Evaporation
`src/thermo0d/physics/evaporation.py` implementiert aktuell einen vorgegebenen Evaporations-Sinkterm als Energiekühlung im konfigurierten Fenster.

Wichtig:
- derzeit **keine** separate Flüssigphase
- derzeit **keine** eigene Kraftstoff-Massenbilanz
- derzeit **keine** physikalische Verdampfungsrate aus Tropfen-/Filmzustand

### RHS
`src/thermo0d/physics/rhs.py` assembliert damit im Wesentlichen:
- Massenbilanz
- Enthalpieströme aus Verbindungen
- `p*dV`
- Wandwärme
- Verbrennung
- Evaporation

Die Datei enthält weiterhin die zentrale Differentialgleichung und Jacobian-Unterstützung, nicht mehr aber die komplette lokale Modelllogik im Detail.

## `run_simulation.py`

Das Skript unterstützt echte CLI-Argumente oder vordefinierte Presets über `simulated_args`.

Verhalten:
- mit CLI-Argumenten: normale Ausführung
- ohne CLI-Argumente: Nutzung von `SELECTED_PRESET`

Aktuelle Presets:
- `project_A156A1` (**Default**)
- `project_default`
- `project_1cyl_2t`
- `project_1cyl_4t`
- `variant_batch`
- `variant_batch_dry_run`
- `testcase_4t_base`
- `testcase_2t_base`

## Konfigurations-Versionierung / Migration

Aktueller Stand:
- `CURRENT_CONFIG_SCHEMA_VERSION = 4`
- alte Konfigurationen werden in den relevanten Editoren erkannt
- vor der Migration wird ein Hinweisdialog gezeigt
- bei Bestätigung erfolgt eine **echte inhaltliche Migration**, nicht nur ein Versionsstempel
- `ConfigLoader` migriert ältere Konfigurationen zusätzlich auch beim normalen Laden im Speicher

Beispiele für automatisch migrierte Felder:
- `csv_sep` / `csv_delimiter` → `csv_separator`
- `simulation.solver.method` → `kind`
- `sampling.mode: angle` → `crank_angle`
- `step_ca_deg` → `step_deg`
- `alphak_file` → `alpha_k_file`
- `forward_discharge_coefficient` / `reverse_discharge_coefficient` → `forward_cd` / `reverse_cd`

## Startbedingungen

Neue Konfigurationen sollen bevorzugt diese Felder verwenden:

```yaml
initial_pressure_Pa: 101325.0
initial_temperature_K: 300.0
```

Ältere Dateien mit `initial_mass_kg` bleiben lesbar und werden als Fallback unterstützt.

## Ausgabe / Sampling

`postprocessing.sampling` unterstützt:
- `time` mit `step_s`
- `crank_angle` mit `step_deg`

Optional kann zusätzlich ein letzter Arbeitszyklus auf festem Winkelraster exportiert werden:

```yaml
postprocessing:
  final_cycle_uniform_angle_export:
    enabled: true
    step_deg: 1.0
```

Dabei gilt bewusst:
- 2T: `0…359°`
- 4T: `0…719°`

so dass kumulierte Größen am Dateiende nicht auf den Zyklusursprung zurückspringen.

## Ergebnis-Checkreport für den letzten Zyklus

Über `postprocessing.check_report` kann zusätzlich zum normalen CSV-Export ein automatischer Prüfbericht für den letzten Zyklus geschrieben werden.

```yaml
postprocessing:
  check_report:
    enabled: true
    html_enabled: false
```

Ausgaben:
- `<csv_path>_check_report.csv`
- Konsolenreport mit Einzelmetriken plus Geometriezeilen
- optional `<csv_path>_check_report.html` als formatierter HTML-Bericht

Der Checkreport enthält unter anderem:
- Punktzahl und Winkelbereich des letzten Zyklus
- `pmin`, `pmax`, `Tmin`, `Tmax`, `mmin`, `mmax`
- integrierte Zyklusgrößen für Masse, Enthalpie, Wandwärme, zugeführte Energie, Verdampfungsenthalpie und Kolbenarbeit
- Massen- und Energiebilanzrestgrößen absolut und relativ
- `overall_status` als Gesamtampel
- Zylindergeometrie in mm / mm² / cm³: `bore_mm`, `stroke_mm`, `conrod_mm`, `bore_area_mm2`, `swept_cm3`, `clearance_cm3`
- Ventilgeometrie in mm / mm²: `lift_max_mm`, `A_ref_mm2`, `A_eff_forward_max_mm2`, `A_eff_reverse_max_mm2`
- bei Slot-Fällen zusätzlich die maximalen Slotflächen, inkl. `A_eff_forward_max_mm2` und `A_eff_reverse_max_mm2`

Die Ampel wird nicht mehr mit einem einzigen starren Satz Grenzwerte bewertet, sondern abhängig von einer automatisch erkannten Fallklasse:
- `closed_or_settling`
- `coldflow_gas_exchange`
- `fired_gas_exchange_4T`
- `fired_scavenged_2T`

Damit werden geschlossene Setzfälle strenger bewertet als durchgesetzte Motorfälle, und gezündete 2T/4T-Fälle erhalten passendere Druck-, Temperatur- und Bilanzgrenzen.

Zusätzlich gilt jetzt für die Lauf-Ausgabe:
- Exportartefakte (`csv`, `xlsx`, Plotdateien, Checkreport-Dateien) werden in der Konsole nur noch mit `OK`, `WARN` oder `FAILED` gemeldet.
- Vollständige Pfade und Verzeichnisse werden dafür nicht mehr in die Konsole geschrieben.

## Tabellen-Loader / `alpha_k_file`

Der Loader für `alpha_k_file` erkennt jetzt robust, ob die Lift-Achse in mm statt m vorliegt. Die Autokonvertierung nach m greift, wenn mindestens eines davon zutrifft:
- Header-Hinweis wie `lift_mm`, `hub_mm` oder vergleichbar
- offensichtlicher Wertebereich der Liftspalte (z. B. 1 … 10 statt 0.001 … 0.010)

Dieselbe mm→m-Logik wird jetzt sowohl im Simulations-Loader als auch in der GUI-/Editor-Vorschau verwendet.

## Massenstrom-Vorzeichenkonvention

Die interne Strömungsrichtung wird topologisch pro Verbindung über `from_idx -> to_idx` definiert.

Daraus folgt:
- `<connection>_mdot_kg_per_s` ist **positiv** für Strömung in definierter Verbindungsrichtung
- derselbe Wert ist **negativ** bei realer Gegenrichtung
- bilanziert wird mit `-mdot` auf der linken und `+mdot` auf der rechten Seite

Zusätzlich werden exportseitig lesbare Betragssignale gebildet:
- `<cyl>_mdot_in_kg_per_s` immer positiv
- `<cyl>_mdot_out_kg_per_s` immer positiv

## Config-Workflow

### Config-Kern / Validierung
- zusätzliche Bereichs- und Konsistenzprüfungen für Solver, Kinematik, Verbrennung, Verdampfung, Slots und Winkelraster
- schema-sichere Normalisierung über `normalize_config_data(...)`
- Rückwärtskompatibilität bleibt erhalten; Migrationen laufen weiterhin über `migrate_config_data(...)`

### Referenzdateien
- `examples/config_master_reference.yaml` ist die vollständige aktuelle Ausgangsvorlage
- `examples/config_schema_documented.yaml` bleibt die ausführlich kommentierte Dokumentationsvorlage

### Config-Tool

```bash
python scripts/config_tool.py validate  Projekte/config.yaml
python scripts/config_tool.py upgrade   Projekte/config.yaml --output Projekte/config_upgraded.yaml
python scripts/config_tool.py normalize Projekte/config.yaml --output Projekte/config_normalized.yaml
python scripts/config_tool.py explain   Projekte/config.yaml
python scripts/config_tool.py diff      Projekte/config.yaml Projekte/config_normalized.yaml
```

Kommandos:
- `validate`: gegen aktuelles Schema prüfen
- `upgrade`: alte Feldnamen / Altstrukturen migrieren
- `normalize`: kanonische Form schreiben
- `explain`: Kurzfassung oder Pfadinhalt ausgeben
- `diff`: zwei Dateien oder eine Datei gegen die kanonische Form vergleichen

## GUI-Werkzeuge

### EngineGasExchangeEditor
- Bearbeitung von `engine` und `gasexchange`
- Timing-Preview mit rechter Y-Achse für Kolbenweg ab UT oder Zylindervolumen
- Vordergrund-Dialoge und robuste Dateidialoge
- Rückwärtskompatible Konfigurationsmigration

### PlotStyleEditor
- Y-Limits, Y-Min/Y-Max, Major/Minor-Step, Major/Minor-Grid
- X-Presets: `0…360`, `0…720`, `-180…180`, `-360…360`, Auto
- Signalfilter mit Aufklappen, echter Treffer-Markierung, Trefferzähler, erster Treffer direkt sichtbar
- stabiler Inspector ohne Rücksprung auf das erste Element
- Subplots per Drag & Drop zwischen Figures verschiebbar, mit `Strg` kopierbar, inkl. Live-Feedback
- Achsenstil kopieren/einfügen
- Achsenstil auf aktuellen Subplot oder alle Subplots anwenden
- intelligente Auto-Limits aus den tatsächlich verfügbaren Preview-Daten
- nachgezogene Winkel-/Eventlogik passend zu `absolute` und zyklischem Wrap

### TopologyConfigEditor
- Eigenschaften-Panel mit schema-basierten Hinweisen
- Pflichtfelder werden mit `*` markiert
- Tooltips zeigen Typ, Pflichtstatus, Default und erlaubte Werte
- kompakte Kontext-Hinweise pro Root / Cylinder / Plenum / Valve / Slot

## Tests

Für die zuletzt nachgezogenen Physikänderungen wurden insbesondere die folgenden Testpfade erweitert bzw. ergänzt:
- `tests/test_rhs_helpers_extended.py`
- `tests/test_flow_kinematics_extended.py`
- `tests/test_parser_rhs.py`

Diese Tests decken insbesondere ab:
- Referenzierung mit lokalem vs. globalem Winkel
- Wrap-Fenster über den Zyklusursprung
- Parser-/RHS-Kompatibilität nach der Source-Term-Auslagerung


## Postprocessing: Plot-Ausgabe, Layout-Dateien und Konsolen-Schalter

Der Root-Block `postprocessing` unterstützt jetzt zusätzlich konfigurierbare Plot- und Konsolenausgabe:

```yaml
postprocessing:
  csv_path: results/out.csv
  csv_separator: ";"

  sampling:
    mode: crank_angle
    step_deg: 1.0

  final_cycle_uniform_angle_export:
    enabled: true
    step_deg: 1.0

  check_report:
    enabled: true
    html_enabled: true

  plots:
    enabled: true
    source: last_cycle_uniform
    output_dir: results/plots

    pressure_plot:
      enabled: true
      path: results/pressure_last_cycle.png

    layouts:
      auto_create_defaults: true
      entries:
        - enabled: true
          path: plot.yaml
          prefix: ""
        - enabled: true
          path: plot10.yaml
          prefix: plot10

  console:
    run_summary:
      enabled: true
    cycle_summary:
      enabled: true
    check_report:
      enabled: true
    geometry:
      enabled: true
```

### Bedeutung

- `postprocessing.plots.enabled` schaltet die gesamte Plot-Generierung.
- `postprocessing.plots.source` wählt die Datenbasis für Standardplots und Layout-Rendering:
  - `last_cycle_uniform`: letzter Zyklus auf festem Winkelraster
  - `export_rows`: normale Exporttabelle
- `postprocessing.plots.output_dir` setzt optional einen Zielordner für mit `plot.yaml`-Layouts erzeugte Grafiken.
- `postprocessing.plots.pressure_plot.*` steuert den einfachen Standard-Druckplot separat.
- `postprocessing.plots.layouts.auto_create_defaults` erzeugt bei Bedarf `plot.yaml` und `plot10.yaml`, falls keine Einträge angegeben sind.
- `postprocessing.plots.layouts.entries` ist eine Liste externer Plot-Layout-Dateien mit optionalem Präfix.
- `postprocessing.console.*` schaltet die Konsolenabschnitte für Run-Summary, Cycle-Summary, Checkreport und Geometrie getrennt.

### Editoren und Migration

Die neuen Felder sind integriert in:
- Pydantic-Config-Modelle (`src/thermo0d/config/models.py`)
- Config-Migration (`src/thermo0d/config_versioning.py`)
- Schema-/Hint-Metadaten (`src/thermo0d/config/schema_meta.py`)
- Topology-Config-Editor (`src/thermo0d/gui/topology_config_editor.py`)
- Runner-Orchestrierung (`src/thermo0d/app/runner.py`)

Im Topology-Editor ist `postprocessing.plots.layouts.entries` als YAML-Mehrzeilenfeld editierbar.

## Konsolenstatus und Timing

Der Lauf gibt jetzt zusätzlich Status- und Timingzeilen für die wichtigsten Schritte aus:

- `[run] wall_clock_s=... solver=...` misst den Ausführungsteil im `SimulationExecutor`
- `[analysis:cycle-index]`, `[analysis:cycle-summary]` messen die Analyse direkt nach dem Solver
- `[postprocessing:*]` zeigen Filterung, Sampling, Rekonstruktion, Integrale und Gesamtzeit
- `[csv]`, `[xlsx]`, `[csv:last-cycle-uniform]`, `[csv:check-report]`, `[html:check-report]` zeigen Status plus Laufzeit
- `[plot]`, `[plot.yaml]`, `[plot10.yaml]` zeigen Status plus Laufzeit der Plot-Erzeugung

Die frühere Gesamtliste aller Zyklen am Ende wird nicht mehr zusätzlich ausgegeben. Bei SciPy-Solvern bleiben die Live-Zykluszeilen während der Integration erhalten.

## Ablageort für `plot.yaml`-Dateien

Layout-Dateien aus `postprocessing.plots.layouts.entries[].path` werden relativ zur verwendeten YAML-Konfigurationsdatei aufgelöst.

Beispiel:

```yaml
postprocessing:
  plots:
    layouts:
      entries:
        - enabled: true
          path: plot.yaml
          prefix: ""
        - enabled: true
          path: plots/plot10.yaml
          prefix: plot10
```

Dann wird `plot.yaml` im selben Ordner wie die Config gesucht und `plots/plot10.yaml` relativ zu diesem Ordner.


### Vollständiges Beispiel

Eine vollständige Beispielkonfiguration auf Basis des A156A1-2V-REX-WH02-Vibe-Falls mit allen Postprocessing-Optionen liegt unter:

- `examples/A156A1-2V-REX-V09d_WH02-Vibe_postprocessing_full.yaml`
