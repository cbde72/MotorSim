# thermo0d v0.4

## Konsolidierter Stand vom 03.04.2026

Dieses Archiv enthält den konsolidierten Gesamtstand aller heute umgesetzten Änderungen, inklusive des Phase-A-Umbaus für einen separaten Freikolben-Architekturpfad. Der Fokus liegt auf einem datengetriebenen 0D-Kreisprozess-Framework mit klarer Trennung von Eingabe, Rechenkern, Ausgabe und GUI-Werkzeugen.

Enthalten sind zusätzlich die nachgezogenen Konsolidierungs-Hotfixes für die zuletzt ausgelieferten Pakete:
- generische Beispieldaten unter `Projekte/data/`, `Projekte/variants/data/` und `examples/data/` wieder vervollständigt (`intake_valve_lift.csv`, `exhaust_valve_lift.csv`, `slot_cd_table.csv` sowie ergänzende `intake_alpha_k.csv` und `exhaust_alpha_k.csv`)
- Topology-Editor: fehlende `schema_meta`-Imports behoben (`meta_for`, `SOLVER_KINDS`, `SAMPLING_MODES`, `ANGLE_REFERENCES`, `PROFILE_ANGLE_DOMAINS`)
- Topology-Editor: deaktivierte Teilmodelle werden beim Speichern bereinigt und rückwärtskompatibel geladen
- Matrix-Builder: `combustion.model: none` und `evaporation.model: none` werden robust verarbeitet
- Topologie: `environment`-Volumina mit festen Zuständen `pressure_Pa` / `temperature_K` und `orifice`-Verbindungen als Drosselpfad
- Wandwärme: komplette Wall-Heat-Logik in `src/thermo0d/physics/heat_transfer.py` zentralisiert; `rhs.py` und `output/rows.py` nutzen jetzt denselben Helper für den Woschni-Pfad


### Zusatzupdate vom 03.04.2026 – Free-Piston Phase A.2

Dieses Archiv enthält jetzt zusätzlich den **minimal lauffähigen Free-Piston-RHS für Phase A.2**.

Neu in A.2:
- eigener Free-Piston-RHS in `src/thermo0d/model/free_piston/rhs.py`
- numerisch lauffähige Integration von **Zylindermasse `m`, innerer Energie `U`, Kolbenposition `x` und Kolbengeschwindigkeit `v`**
- freie Geometrie über `cylinder_volume_from_position(...)` und `cylinder_dvdt_from_velocity(...)`
- Minimalthermodynamik in `src/thermo0d/model/free_piston/thermo.py`
- Free-Piston-Solverpfad in `src/thermo0d/model/free_piston/simulator.py`
- zeitbasierte Minimal-Postprocessing-Ausgabe für Free Piston ohne Winkel-/Zyklusrekonstruktion
- RHS-Hotpath bleibt **frei von Dict-Zugriffen**; der Rechenkern arbeitet nur mit Arrays, Skalarwerten und den strukturierten Bundle-Feldern, damit der Pfad in derselben Richtung **numba-kompatibel** bleibt wie das klassische/conventional Modell

A.2 verwendet im aktuellen Archiv die bereits vorhandenen Free-Piston-Konfigurationsblöcke:
- `free_piston.initial_conditions`
- `free_piston.mechanics`
- `free_piston.friction`
- `free_piston.load`
- `free_piston.bounce`

Die minimale A.2-Mechanik koppelt:
- Zylinderdruckkraft
- Bounce-Gasfeder
- Coulomb-/viskose Reibung
- viskose Last

Noch **nicht** Teil von A.2 sind:
- Verbrennung
- Verdampfung
- winkelgeführte Ventilprofile
- klassisches theta-/cycle-basiertes Reporting für den Free-Piston-Zweig

### Wesentliche Änderungen dieses Stands
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
- RHS-Hot-Path bereinigt: zusammengefasste Zylinder-Kinematik, direkter Wandwärme-Kontext und weniger doppelte Flächen-/Trigonometrie-Auswertung
- PlotStyleEditor und Plot-Layout nutzen bei theta-basierten CSV-Previews im Datenmodus jetzt den **realen X-Datenbereich** statt hart auf `0…360/720°` zu klemmen; ein letzter Wert `719` bleibt damit auch visuell bei `719` ohne künstliche Strecke zum Ursprung
- `run.log` enthält jetzt zusätzlich zur letzten Zyklusdauer auch die **gesamte Simulationslaufzeit** als `simulation_wall_clock_s`
- CSV-Export ergänzt pro Zylinder die Spalten `<cyl>_heat_transfer_power_W` und `<cyl>_htc_W_per_m2K`; die bestehende Spalte `<cyl>_wall_heat_W` bleibt aus Kompatibilitätsgründen erhalten

## Zusatzupdate vom 01.04.2026

Dieses Patch-Update zieht den **RHS-Hot-Path** in `src/thermo0d/physics/rhs.py` nach und aktualisiert die Dokumentation auf denselben Stand.

Neu in diesem Patch:
- RHS intern klar in **Zustandsrekonstruktion**, **Verbindungsströmung** und **lokale Energieterme** gegliedert
- neue Hot-Path-Hilfe `cylinder_kinematic_state_from_time(...)` in `src/thermo0d/physics/kinematics.py`, damit Volumen, `dV/dt`, Kurbelwinkel, Kolbenweg und Winkelgeschwindigkeit pro Zylinder nur noch **einmal** berechnet werden
- Wandwärme im RHS direkt über `wall_heat_rate_from_row(...)` mit bereits rekonstruiertem Zylinderkontext, statt den Kontext im heißen Pfad erneut aus `vol_row` und `kin_matrix` abzuleiten
- Verbindungsquerschnitte im RHS über einen gemeinsamen Helper `_connection_area_and_coefficients(...)` zusammengeführt
- `_evaluate_valve_area(...)` entschlackt: keine unnötige doppelte Rückrechnung über `_evaluate_valve_state(...)` mehr
- analytischer Flow-Jacobian nutzt denselben zusammengefassten Zylinder-Kinematikpfad für bessere Konsistenz und weniger doppelte Trigonometrie

Ergebnis:
- bessere Lesbarkeit des Rechenkerns
- weniger verstreute Speziallogik im RHS
- geringerer Overhead pro RHS-Aufruf, vor allem bei mehreren Zylindern und vielen inneren Integrationsschritten

Zusätzliche Nachzüge in diesem Stand:
- Preview- und Auto-Plot-Achsen für theta-basierte CSV-Daten skalieren im Datenmodus jetzt bis zum **letzten real vorhandenen X-Wert**
- `ResultRowBuilder` nutzt für Zylinder den zusammengefassten Kinematikpfad `cylinder_kinematic_state_from_time(...)` statt Volumen, Kolbenweg und Winkelgeschwindigkeit separat zu berechnen
- Wandwärme-CSV-Spalten werden mit einem gemeinsamen Helper für **Wärmeleistung und HTC** aufgebaut, damit die Woschni-Zwischengröße nicht doppelt hergeleitet werden muss
- `run.log` enthält zusätzlich `simulation_wall_clock_s` für die gesamte Simulationsdauer des aktuellen Laufs


## Woschni-Varianten / Wandwärme

Das Wandwärmemodell `wall_heat.model: woschni` unterstützt jetzt mehrere Untervarianten:
- `variant: legacy` – bisheriges Projektmodell mit den Legacy-Koeffizienten `c1/c2/c3`
- `variant: promo` – Quellen-/Legacy-Modell aus dem historischen Code (`WoschniPromo`)
- `variant: classic` – klassische Woschni-Variante
- `variant: swirl` – klassische Woschni-Variante mit `swirl_number`
- `variant: gt` – GT-nahe WoschniGT-Variante
- `variant: huber` – Huber-Variante mit zusätzlicher IMEP-/Volumenkorrektur

Neue Konfigurationsfelder unter `wall_heat:`:
- `variant`
- `multiplier`
- `cucm`
- `swirl_number`
- `imep_bar`
- `dp_mode`
- `reference_state_mode`
- `phase_mode`
- `c1/c2/c3` bleiben für `variant: legacy` erhalten

Praktische Empfehlung:
- für quellennahe Läufe `variant: promo` verwenden
- zunächst `dp_mode: off` beibehalten
- danach `multiplier`, `cucm`, `swirl_number` oder `imep_bar` kalibrieren

Eine kommentierte Beispielkonfiguration liegt unter:
- `examples/config_woschni_variants_documented.yaml`

## Architektur

Die Codebasis trennt strikt zwischen:
- **Input**: Laden, Validieren, Auflösen von Pfaden, Aufbau kompakter Simulationsdaten
- **Compute**: Solver, Integrationslauf, Kennwerte
- **Output**: Sampling, Zeilenaufbau, CSV-/Excel-Export, Konsolenreporting
- **App/GUI**: Orchestrierung, Editoren, Werkzeuge

Der physikalische Rechenkern ist damit von YAML-Dateien, Exportformaten und GUI-Code getrennt.


## Freikolben / Phase A

Der Umbauplan für den Freikolbenpfad wurde in **Phase A** auf die Codebasis angewendet. Der Stand ist bewusst architekturorientiert und trennt den neuen Pfad sauber vom bestehenden Kurbeltrieb-Modell.

Enthalten in diesem Patch:
- neues Top-Level-Feld `modeling.architecture` mit den Werten `classic` und `free_piston`
- neue Top-Level-Sektion `free_piston` für Startbedingungen und mechanische Metadaten
- eigener Builder-Zweig für `free_piston`
- generisches `StateLayout`, damit zusätzliche Zustände nicht mehr implizit auf `2 * n_vol` fest verdrahtet sind
- neue Zustände `free_piston_x_m` und `free_piston_v_m_per_s` im Bundle / Zustandsvektor
- eigener Modellbaum `src/thermo0d/model/` mit `conventional/` für den klassischen Kurbeltrieb und `free_piston/` für den neuen Freikolbenpfad

Wichtig:
- Der **bestehende Solverpfad für klassische Fälle bleibt unverändert**.
- Der neue Freikolbenpfad ist in Phase A **absichtlich noch nicht ausführbar**. Ein Run mit `modeling.architecture: free_piston` wird deshalb mit einer klaren Meldung abgebrochen, statt unvollständige oder irreführende Physik zu rechnen.
- Phase B ist der nächste Schritt für translatorische Mechanik, Volumen `V(x)`, Kräfte und RHS.

Beispiel für den neuen Architekturumschalter:

```yaml
modeling:
  architecture: free_piston

free_piston:
  initial_conditions:
    x0_m: -0.008
    v0_m_per_s: 0.4
    cylinder:
      pressure_Pa: 101325.0
      temperature_K: 300.0
    bounce:
      pressure_Pa: 140000.0
      temperature_K: 300.0
    combustion_state:
      burned_fraction_0to1: 0.0
      released_energy_J: 0.0
      ignition_armed: false
      injection_armed: false
  mechanics:
    moving_mass_kg: 2.0
    piston_area_m2: 0.00436
    clearance_volume_m3: 2.5e-05
    x_min_m: -0.04
    x_max_m: 0.04
  friction:
    model: coulomb_viscous
    fc_N: 20.0
    cv_Ns_per_m: 10.0
  load:
    model: viscous
    damping_Ns_per_m: 120.0
  bounce:
    model: gas_spring
    chamber_volume0_m3: 3.0e-04
    p0_Pa: 150000.0
    polytropic_exponent: 1.30
```

## Neue 2T-Varianten auf Basis A156A1

Zusätzlich wurden unter `Projekte/variants/` drei neue 2-Takt-Varianten auf Basis von `Projekte/A156A1-2V-REX-V09d_WH02-Vibe_PP_RK45.yaml` abgelegt:
- `A156A1-2T-VLV-Vibe_PP_RK45.yaml` – 2T mit Ventilsteuerung
- `A156A1-2T-SLTang-Vibe_PP_RK45.yaml` – 2T mit schlitzgesteuerter, winkelabhängiger Öffnung
- `A156A1-2T-SLTpos-Vibe_PP_RK45.yaml` – 2T mit schlitzgesteuerter, kolbenpositionsabhängiger Öffnung

Hinweis: Die neuen Varianten übernehmen die bestehende A156A1-Basisstruktur, stellen aber die referenzierten Ventil-/AlphaK-Dateien auf die im Archiv tatsächlich vorhandenen generischen `data/*.csv`-Dateien um, damit die Varianten unmittelbar auflösbar und baubar bleiben.

## Paketstruktur

```text
src/thermo0d/
├─ app/
├─ compute/
├─ config/
├─ core/
├─ gui/
├─ input/
├─ model/
│  ├─ conventional/
│  └─ free_piston/
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
- `thermo0d.model.conventional.builder.build_conventional_bundle`
- `thermo0d.model.free_piston.builder.build_free_piston_bundle`

### Compute
- `thermo0d.compute.solvers.SolverFactory`
- `thermo0d.compute.executor.SimulationExecutor`
- `thermo0d.compute.analysis.CycleSummaryCalculator`

### Physics
- `thermo0d.physics.kinematics`
- `thermo0d.physics.flow`
- `thermo0d.physics.heat_transfer`
- `thermo0d.physics.rhs`
  - Rekonstruktionspfad: Zustand, Kinematik, Druck/Temperatur
  - Verbindungsfluss: Ventil/Slot/Orifice über gemeinsamen Flächen-Helper
  - lokale Energieterme: `p*dV`, Wandwärme, Vibe, Evaporation

### Output
- `thermo0d.output.sampling.OutputSampler`
- `thermo0d.output.rows.ResultRowBuilder`
- `thermo0d.output.exporters.CsvExporter` / `ExcelExporter`
- `thermo0d.output.console.ConsoleCycleReporter`
- `thermo0d.output.service.PostprocessingService`

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
- `CURRENT_CONFIG_SCHEMA_VERSION = 5`
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

Für Zylinder exportiert die CSV zusätzlich zu den bisherigen Bilanzgrößen jetzt auch:
- `<cyl>_heat_transfer_power_W` als klare Alias-Spalte für die Zylinder-Wärmeleistung
- `<cyl>_htc_W_per_m2K` als momentanen Heat-Transfer-Coefficient der Wandwärme-Korrelation


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

### TopologyConfigEditor
- Eigenschaften-Panel mit schema-basierten Hinweisen
- Pflichtfelder werden mit `*` markiert
- Tooltips zeigen Typ, Pflichtstatus, Default und erlaubte Werte
- kompakte Kontext-Hinweise pro Root / Cylinder / Plenum / Valve / Slot

### Alias-Editor
- robuste Fehlerdialoge
- exakte Dateipfade
- optionaler Start ohne Auto-Generierung

## Doc-Editor / 404-Fix

Unter `doc/` liegt ein statischer Browser-Editor. Relevante Dateien:
- `doc/index.html`
- `doc/app.js`
- `doc/data.js`
- `doc/README.md`

Damit funktioniert der Editor ohne die früheren 404-Probleme auf fehlende JS-Dateien.

## Tests

`python scripts/test_runner.py` startet `pytest`, erzeugt JUnit-XML und zusätzlich `test_cases/index.html`.

Die Tests decken unter anderem ab:
- Konfigurationsvalidierung und Fehlerformatierung
- Pfadauflösung und CLI
- Solver-Registry inkl. stiff solver
- Kinematik und Massenstrom
- Output-Sampling und letzter Zyklus
- Konfigurationsmigrationen
- Plot-Editor-Verhalten (Axis-Inspector, Signalfilter, DnD)

## Archivbereinigung

Aus dem ausgelieferten Archiv entfernt bzw. nicht mehr Bestandteil des konsolidierten Stands:
- lose Wrapper-/Legacy-Dateien
- `*_orig` / `*.orig`
- nicht benötigte Cache-/Build-Reste
- generierte `test_cases`-Work-Verzeichnisse, Laufartefakte und Plot-Dateien
- temporäre Normalisierungs-/Prüfdateien aus Zwischenständen

Beispieldateien liegen jetzt unter:
- `examples/`
- `Projekte/data/`

## Skript-Startpunkte

```bash
python scripts/run_simulation.py
python scripts/run_plot_editor.py --project Projekte
python scripts/run_gasexchange_editor.py --project Projekte
python scripts/run_alias_editor.py --project Projekte
python scripts/run_topology_config_editor.py
python scripts/run_doc_editor.py
python scripts/config_tool.py validate Projekte/config.yaml
python scripts/test_runner.py
```

## Versionsstände
- Package-Version: `7.1.56`
- Config-Schema-Version: `4`

## Pflegehinweis

Diese `README.md` beschreibt den konsolidierten Ist-Stand dieses ZIP-Archivs und wird bei Änderungen am ausgelieferten Paket mitgeführt.


## Umgebung und Drossel in der Topologie

Zusätzlich zu `cylinder` und `plenum` unterstützt die Topologie jetzt den Volumentyp `environment` als feste Randbedingung mit konstantem Druck und konstanter Temperatur. Für Verbindungen ist der Typ `orifice` als stationäre Drossel verfügbar.

Beispiel:

```yaml
preprocessing:
  volumes:
    - name: intake_env
      type: environment
      pressure_Pa: 101325.0
      temperature_K: 293.15
    - name: intake_plenum
      type: plenum
      initial_pressure_Pa: 101325.0
      initial_temperature_K: 293.15
      fixed_volume_m3: 0.003
      wall_heat: {model: none}
      combustion: {model: none}
      evaporation: {model: none}
  connections:
    - name: intake_throttle
      type: orifice
      from_volume: intake_env
      to_volume: intake_plenum
      area_m2: 1.0e-4
      forward_cd: 0.7
      reverse_cd: 0.7
```

Semantik:
- `environment` ist eine feste Randbedingung. `pressure_Pa` und `temperature_K` bleiben während der Simulation konstant.
- `orifice` verwendet die isentrope Drosselgleichung mit separaten `forward_cd`- und `reverse_cd`-Werten.
- `environment` kann direkt im Topologie-Editor angelegt werden; `orifice` ist dort als Drossel verfügbar.


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

## Output-Verzeichnis

Simulationsergebnisse werden zentral in ein Laufverzeichnis unterhalb von `results/` geschrieben.

- Standard: Name der verwendeten Konfigurationsdatei ohne Extension, auf 15 Zeichen gekürzt
- Override: `postprocessing.outdir`
- Das Laufverzeichnis selbst liegt unter `results/<kurzname>`
- CSV-, XLSX- und daraus abgeleitete Tabellen-/Report-Dateien liegen unter `results/<kurzname>/results/`
- gerenderte Plotdateien liegen unter `results/<kurzname>/plots/`
- Config-/Daten-Snapshot bleiben direkt im Laufverzeichnis `results/<kurzname>/`
- `run.log` und `fail.log` bleiben zentral unter `test_cases/`

Beispiel:

```yaml
postprocessing:
  outdir: mein_lauf_01
```



## Output-Verzeichnis-Logik
- Ergebnisse landen unter `results/<kurzname>` mit kollisionssicherer 15-Zeichen-Kurzlogik.
- `postprocessing.outdir` überschreibt den Basisnamen, bleibt aber ebenfalls auf 15 Zeichen begrenzt und kollisionssicher.
- CSV/XLSX/Check-Report/Last-Cycle-CSV landen unter `results/<kurzname>/results/`.
- Plotbilder landen unter `results/<kurzname>/plots/`.
- `run.log` und `fail.log` bleiben zentral unter `test_cases/`.
