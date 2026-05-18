# Thermo0D / MotorSim - zusammengefuehrte Markdown-Dokumentation

Diese Datei fasst die Markdown-Dateien aus `doc/` zusammen. Die Reihenfolge ist so chronologisch wie aus Dateizeitstempeln und Dateinamen ableitbar. Die Originaldateien bleiben erhalten.

## Quellenreihenfolge

1. `README.md` - 2026-04-21 09:38:58
2. `FREE_PISTON_THERMO_COMPONENTS_NOTES.md` - 2026-04-21 15:36:20
3. `PATCH_NOTES_burned_unburned.md` - 2026-04-21 15:36:20
4. `PATCH_NOTES_burned_unburned_v2.md` - 2026-04-21 15:36:20
5. `PHASE1_MASS_MODEL_NOTES.md` - 2026-04-21 15:36:20
6. `PHASE1_PHASE2_COMBINED_NOTES.md` - 2026-04-21 15:36:20
7. `README - Kopie.md` - 2026-04-21 15:36:20
8. `README_INJECTOR_STAGE1.md` - 2026-04-21 15:36:20
9. `README_INJECTOR_STAGE2_COMBUSTION_BALANCE.md` - 2026-04-21 15:36:20
10. `README_plot.md` - 2026-04-21 15:36:20
11. `README_quellen_step1.md` - 2026-04-21 15:36:20
12. `README_updated - Kopie.md` - 2026-04-21 15:36:20
13. `README_updated.md` - 2026-04-21 15:36:20
14. `STROKE_FRAME_EXPORT_QUICKSTART.md` - 2026-04-22 07:51:05
15. `README_project.md` - 2026-05-12 07:41:13

---

## Quelle: README.md

Zeitstempel: `2026-04-21 09:38:58`

# Thermo0D Doc Editor (installationsfrei)

Dieser `doc/`-Ordner enthÃ¤lt eine statische Browser-OberflÃ¤che fÃ¼r die aktuelle `config.yaml`.

## Eigenschaften

- keine lokale Installation mit `npm` erforderlich
- statische Dateien direkt im Archiv enthalten: `index.html`, `styles.css`, `data.js`, `app.js`
- feste Navigation links
- feste Formelvorschau oben
- Live-YAML-Vorschau im Browser
- kleine Demo-Kurven mit Plotly
- explizite Hinweise zur Konfigurationsversionierung und Schema-Migration

## Start

Direkt im Browser:

```text
/doc/index.html
```

oder per kleinem lokalen Python-Server:

```bash
python scripts/run_doc_editor.py
```

Dann Ã¶ffnet sich der Editor unter `http://127.0.0.1:8765/doc/index.html`.

## Wichtiger Hinweis zum 404-Fehler

`index.html` referenziert jetzt die mitgelieferten Dateien `data.js` und `app.js` im selben Ordner.
Der frÃ¼here 404 auf `127.0.0.1` trat auf, wenn diese JavaScript-Dateien im Archiv fehlten.
Im aktuellen Stand sind beide Dateien enthalten.

## UI-Stack

Der statische Editor nutzt CDN-basiert:

- Tailwind CSS
- KaTeX fÃ¼r Formelkarten
- SweetAlert2 fÃ¼r Aktionen und Feedback
- Phosphor Icons
- Plotly fÃ¼r technische Diagramme

Es ist keine lokale Paketinstallation notwendig.
FÃ¼r CDN-Ressourcen ist beim Ã–ffnen eine Internetverbindung sinnvoll.

## Konfigurationsversionierung

Die BeispieloberflÃ¤che dokumentiert jetzt Schema v4.
In den Desktop-Editoren werden beim Laden alter Konfigurationen nach BestÃ¤tigung automatische Migrationen ausgefÃ¼hrt, unter anderem:

- `postprocessing.csv_sep` beziehungsweise `csv_delimiter` â†’ `csv_separator`
- `simulation.solver.method` â†’ `kind`
- `preprocessing.features.heat_transfer` â†’ `wall_heat`
- `sampling.mode: angle` â†’ `crank_angle`
- `step_ca_deg` â†’ `step_deg`
- `angle_ref`, `opening_ref`, `alphak_file`, `number_of_holes` â†’ aktuelle Feldnamen
- ErgÃ¤nzung von `postprocessing.final_cycle_uniform_angle_export`

---

## Quelle: FREE_PISTON_THERMO_COMPONENTS_NOTES.md

Zeitstempel: `2026-04-21 15:36:20`

# Free-Piston Thermo Components Patch

Dieser Patch ist als **Korrektur-/Konsolidierungspatch auf Basis von Phase 1 + Phase 2** gedacht.

Er stellt den Free-Piston-Thermopfad so um, dass die Stoffwerte `p`, `T`, `R`, `cp`, `cv`, `kappa`
nicht mehr aus `m_total + lambda(total,fuel)` kommen, sondern aus der reduzierten Mischung:

- frische Luft
- Kraftstoffdampf
- verbranntes Gas

## Umgestellt in

- `src/thermo0d/model/free_piston/rhs.py`
- `src/thermo0d/model/free_piston/postprocessing.py`
- `src/thermo0d/output/reconstruction.py`
- `src/thermo0d/physics/quellen_props.py`

## Technische Wirkung

Neue MischungseingÃ¤nge fÃ¼r den Free-Piston-Pfad:

- `m_air`
- `m_fuel_vapor`
- `m_burned`

Neue reduzierte Stoffwertfunktionen:

- `lambda_from_air_and_fuel_mass(...)`
- `properties_from_mass_energy_components_quellen(...)`
- `pressure_from_mass_energy_components_quellen(...)`

## Erwartete Basis

Der Patch setzt den Phase-1-Zustandsraum bereits voraus:

- `m_gas`
- `U`
- `m_burned`
- `m_air`
- `m_fuel_liquid`

und damit die StateLayout-Helfer:

- `air_mass_from_state(...)`
- `fuel_vapor_mass_from_state(...)`
- `burned_mass_from_state(...)`

## Verifikation

GeprÃ¼ft auf dem kombinierten Stand aus Originalarchiv + `phase1_phase2_combined_patch.zip`:

- `python -m compileall src/thermo0d` erfolgreich
- Bundle-Aufbau fÃ¼r `Projekte/variants/free_piston_GenSet_V09f.yaml` erfolgreich
- `compute_free_piston_rhs(0.0, y_init, bundle)` liefert endliche Werte

---

## Quelle: PATCH_NOTES_burned_unburned.md

Zeitstempel: `2026-04-21 15:36:20`

# Burned / Unburned Masse â€“ Projektweiter Umbau

## Ziel
Projektweiter Einbau einer verbrannten / unverbrannten Massenabbildung, sodass:
- verbranntes Gas Ã¼ber alle Verbindungen mitgefÃ¼hrt wird,
- verbranntes Gas aus dem Zylinder ausgespÃ¼lt werden kann,
- dieses Restgas in Plena / Receiver / Bounce-Seite verbleiben und spÃ¤ter wieder angesaugt werden kann,
- die unverbrannte Masse im Zylinder separat auswertbar ist.

## Umgesetztes Modell
Pro Volumen werden jetzt drei thermodynamische ZustÃ¤nde gefÃ¼hrt:
1. `m_kg` = Gesamtmasse
2. `U_J` = innere Energie
3. `m_burned_kg` = verbrannter Massenanteil (Tracer)

Die unverbrannte Masse wird daraus abgeleitet:
- `m_unburned_kg = max(m_kg - m_burned_kg, 0)`

## Transport Ã¼ber Verbindungen
FÃ¼r alle MassestrÃ¶me (Valve, Slot, Orifice, Check-Valve) wird zusÃ¤tzlich der verbrannte Anteil des Upstream-Volumens advectiv mitgefÃ¼hrt:
- Burned-Massenstrom = `mdot * burned_fraction_upstream`

Damit kann verbranntes Gas aus dem Zylinder in Receiver / Exhaust-Plenum gelangen und von dort spÃ¤ter wieder in den Zylinder zurÃ¼cktransportiert werden.

## Reaktionsabbildung im Zylinder
Die Verbrennung wandelt jetzt nicht nur Energie um, sondern verschiebt auch Masse vom unverbrannten in den verbrannten Anteil.

Dazu wird aus der Vibe-Funktion die momentane Burned-Fraction-Dynamik abgeleitet. Der Massenumsatz wird als Quelle auf `m_burned_kg` aufgebracht.

## Free-Piston Lambda-Latch
Die Free-Piston-Lambda-Latch-Logik verwendet jetzt nicht mehr die gesamte Zylindermasse, sondern die **unverbrannte** Zylindermasse als Referenz. Damit fÃ¼hrt zurÃ¼ckgesaugtes verbranntes Gas nicht mehr zu einer ÃœberschÃ¤tzung der verfÃ¼gbaren Frischmasse.

## Neue Ausgabesignale
FÃ¼r jedes Volumen werden in den Exporten zusÃ¤tzlich bereitgestellt:
- `<name>_m_burned_kg`
- `<name>_m_unburned_kg`
- `<name>_burned_fraction_0to1`

FÃ¼r den Free-Piston-Sonderexport zusÃ¤tzlich:
- `cylinder_m_burned_kg`
- `cylinder_m_unburned_kg`
- `cylinder_burned_fraction_0to1`

## GeÃ¤nderte Dateien
- `src/thermo0d/core/state_layout.py`
- `src/thermo0d/compute/jacobian.py`
- `src/thermo0d/compute/analysis.py`
- `src/thermo0d/model/conventional/builder.py`
- `src/thermo0d/model/free_piston/builder.py`
- `src/thermo0d/model/free_piston/rhs.py`
- `src/thermo0d/model/free_piston/postprocessing.py`
- `src/thermo0d/model/free_piston/combustion_latch.py`
- `src/thermo0d/output/reconstruction.py`
- `src/thermo0d/output/plots.py`
- `src/thermo0d/physics/combustion.py`
- `src/thermo0d/physics/rhs.py`
- `src/thermo0d/physics/composition.py` (neu)
- `src/thermo0d/gui/signal_catalog.py`

## Smoke-Tests
Erfolgreich getestet mit:
- `Projekte/variants/free_piston_GenSet_V01.yaml`
- `Projekte/variants/free_piston_Vibe_V04.yaml`

Beobachtung im Vibe-Test:
- `cylinder_m_burned_kg` steigt deutlich an,
- `receiver_m_burned_kg` und `exhaust_plenum_m_burned_kg` werden > 0,
- damit ist der Transport verbrannter Masse durch das Netzwerk aktiv.

## Bekannte Vereinfachung
Das Modell verwendet weiterhin ein Ein-Gas-Eigenschaftsmodell (`cp`, `cv`, `R` global konstant). 
Die burned/unburned-Trennung ist daher aktuell eine **Massen-/Tracer-Abbildung** fÃ¼r SpÃ¼lung, Restgas und Re-Ansaugung, noch kein vollstÃ¤ndiges Mehrzonen- oder Mehrstoff-Gemischmodell mit separaten Stoffwerten.

---

## Quelle: PATCH_NOTES_burned_unburned_v2.md

Zeitstempel: `2026-04-21 15:36:20`

# Patch Notes â€“ burned/unburned Erweiterung v2

## Neu in diesem Patch

### 1) Initialer Restgas-/Burned-Anteil bei `x0_m`
FÃ¼r `free_piston.initial_conditions.combustion_state` gibt es jetzt zusÃ¤tzlich:

- `burned_mass_percent` in `%` (0..100)

Weiterhin bleibt `burned_fraction_0to1` nutzbar.

Wirkung:
- Der Builder setzt die anfÃ¤ngliche verbrannte Zylindermasse `m_burned` jetzt real aus dem konfigurierten Startanteil.
- Das gilt auch dann, wenn `postprocessing.auto_update_initial_conditions: false` gesetzt ist.

### 2) Auto-Update der Startwerte
Wenn `auto_update_initial_conditions: true` aktiv ist, schreibt der automatische Restart-Update jetzt zusÃ¤tzlich in die YAML:

- `free_piston.initial_conditions.combustion_state.burned_fraction_0to1`
- `free_piston.initial_conditions.combustion_state.burned_mass_percent`

Damit wird der am letzten Kompressionshub bei `x0_m` vorhandene Restgasanteil mitgefÃ¼hrt.

### 3) README / Last-Cycle
In der generierten `README.md` wird jetzt zusÃ¤tzlich ausgegeben:

- `restgas_anteil_brennbeginn_percent`

Ermittlung:
- aus dem ersten Brennbeginn-Sample des letzten vollstÃ¤ndigen UTâ†’OTâ†’UT-Zyklus
- berechnet als:
  - `m_burned / m_total * 100`

AuÃŸerdem werden jetzt auch `combustion_start_*` ZustandsgrÃ¶ÃŸen in die Last-Cycle-Tabelle aufgenommen, wenn Brennbeginn erkannt wurde.

### 4) Neue Verbindungssignale fÃ¼r Massenstrom-Komponenten
FÃ¼r alle Verbindungen werden jetzt zusÃ¤tzlich rekonstruiert:

- `<connection>_mdot_kg_per_s`
- `<connection>_mdot_unburned_kg_per_s`
- `<connection>_mdot_burned_kg_per_s`

Die Vorzeichenrichtung bleibt identisch zur bisherigen Gesamt-Massenstromdefinition.

### 5) Neue Plot-Dateien
Neu erzeugt:

- `plot-fp_transfer_slot_mass_components.yaml`
- `plot-fp_exhaust_slot_mass_components.yaml`

Beide im Stil der vorhandenen `plot-fp_temperature.yaml`.

## GeÃ¤nderte Dateien

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

---

## Quelle: PHASE1_MASS_MODEL_NOTES.md

Zeitstempel: `2026-04-21 15:36:20`

# Phase 1 â€“ sauberes Massenmodell

## Neues Zustandsmodell pro Volumen

Der thermodynamische Zustandsvektor je Volumen wurde von 3 auf 5 ZustÃ¤nde erweitert:

1. `m_gas_kg`
2. `U_J`
3. `m_burned_kg`
4. `m_air_kg`
5. `m_fuel_liquid_kg`

Abgeleitet wird:

- `m_fuel_vapor_kg = m_gas - m_burned - m_air`
- `m_fuel_total_kg = m_fuel_vapor + m_fuel_liquid`
- `m_unburned_kg = m_gas - m_burned`

## Umgesetzte Punkte

- `StateLayout` auf 5 ZustÃ¤nde pro Volumen erweitert
- Builder fÃ¼r konventionell und Free-Piston initialisieren jetzt `m_air` und `m_fuel_liquid`
- Massentransport in den RHS-Funktionen transportiert jetzt explizit:
  - Gesamt-Gasmasse
  - verbrannte Gasmasse
  - Luftmasse
  - flÃ¼ssiger Kraftstoff bleibt lokal
  - gasfÃ¶rmiger Kraftstoff ergibt sich implizit aus dem Rest
- Verdampfung wirkt jetzt zusÃ¤tzlich als MassenÃ¼bergang:
  - `m_fuel_liquid -> m_gas`
- Verbrennung verschiebt jetzt Masse von unburned nach burned und reduziert explizit die Luftmasse anteilig
- Rekonstruktion/CSV erweitert um:
  - `*_m_air_kg`
  - `*_m_fuel_liquid_kg`
  - `*_m_fuel_vapor_kg`
  - `*_m_fuel_total_kg`
- Free-Piston Latch arbeitet jetzt mit expliziter Luftmasse statt mit `m_unburned`

## Wichtige Grenzen dieses Phase-1-Patches

- `m_fuel_vapor` ist noch **abgeleitet**, nicht eigener expliziter Zustand
- Verbrennung verteilt die Umwandlung aktuell **anteilig nach vorhandener unburned Gasmasse**; es gibt noch **keine harte stÃ¶chiometrische O2-Limitierung**
- Bei lambda-gelatchter Free-Piston-Verbrennung ist die energetische Latch-Logik weiter vorhanden; die Stoffwerte folgen aber jetzt primÃ¤r dem expliziten Massenzustand
- Jacobian-Analytik fÃ¼r den alten 2/3-Zustandsfall bleibt im Code, fÃ¼r den neuen 5-Zustandsfall greift automatisch der FD-Pfad

## Smoke-Test

Erfolgreich getestet:

- Konfig geladen und Bundle gebaut fÃ¼r `free_piston_GenSet_V09f.yaml`
- RHS bei `t=0` erfolgreich ausgewertet
- Python-Compile-Lauf Ã¼ber `src/thermo0d` erfolgreich

---

## Quelle: PHASE1_PHASE2_COMBINED_NOTES.md

Zeitstempel: `2026-04-21 15:36:20`

# Phase 1 + Phase 2 â€“ Massenmodell und reduzierte Mischungs-Stoffwerte

Dieses Patch kann direkt auf das hochgeladene Basisarchiv angewendet werden.

## Enthalten

### Phase 1 â€“ sauberes Massenmodell
Pro Volumen werden nun folgende ZustÃ¤nde gefÃ¼hrt:

- `m_gas`
- `U`
- `m_burned`
- `m_air`
- `m_fuel_liquid`

Abgeleitet:

- `m_fuel_vapor = m_gas - m_air - m_burned`
- `m_fuel_total = m_fuel_vapor + m_fuel_liquid`

### Phase 2 â€“ reduzierte Mischungs-Stoffwerte
Das bisherige Promo-Stoffwertmodell wird fÃ¼r `R`, `cp`, `cv` und `kappa` auf ein reduziertes Dreikomponentenmodell umgestellt:

- frische Luft
- Kraftstoffdampf
- verbranntes Gas

Die DiagnosegrÃ¶ÃŸe `lambda` bleibt erhalten, wird aber aus `m_air` und `m_fuel_vapor` gebildet.

## Kernwirkung

- Verdampfung verschiebt Masse von `m_fuel_liquid` nach `m_gas`
- Luftmasse wird explizit transportiert
- Brennmasse bleibt explizit transportiert
- Stoffwerte werden aus den aktuellen Massenanteilen gemischt
- Export/Rekonstruktion geben die neuen Massen und gemischten Stoffwerte aus

## Validierung

GeprÃ¼ft auf dem hochgeladenen Archiv:

- `python -m compileall src/thermo0d` erfolgreich
- Smoke-Test mit `Projekte/variants/free_piston_GenSet_V09f.yaml` erfolgreich
- `compute_free_piston_rhs(0.0, y_init, bundle)` liefert endliche Werte

## Noch nicht enthalten

- keine vollstÃ¤ndigen NASA-Polynome
- keine explizite O2-limitierte stÃ¶chiometrische Verbrennung
- keine Aufspaltung verbrannter Produkte in Einzelspezies

---

## Quelle: README - Kopie.md

Zeitstempel: `2026-04-21 15:36:20`

# thermo0d v0.4

## Konsolidierter Stand vom 03.04.2026

Dieses Archiv enthÃ¤lt den konsolidierten Gesamtstand aller heute umgesetzten Ã„nderungen, inklusive des Phase-A-Umbaus fÃ¼r einen separaten Freikolben-Architekturpfad. Der Fokus liegt auf einem datengetriebenen 0D-Kreisprozess-Framework mit klarer Trennung von Eingabe, Rechenkern, Ausgabe und GUI-Werkzeugen.

Enthalten sind zusÃ¤tzlich die nachgezogenen Konsolidierungs-Hotfixes fÃ¼r die zuletzt ausgelieferten Pakete:
- generische Beispieldaten unter `Projekte/data/`, `Projekte/variants/data/` und `examples/data/` wieder vervollstÃ¤ndigt (`intake_valve_lift.csv`, `exhaust_valve_lift.csv`, `slot_cd_table.csv` sowie ergÃ¤nzende `intake_alpha_k.csv` und `exhaust_alpha_k.csv`)
- Topology-Editor: fehlende `schema_meta`-Imports behoben (`meta_for`, `SOLVER_KINDS`, `SAMPLING_MODES`, `ANGLE_REFERENCES`, `PROFILE_ANGLE_DOMAINS`)
- Topology-Editor: deaktivierte Teilmodelle werden beim Speichern bereinigt und rÃ¼ckwÃ¤rtskompatibel geladen
- Matrix-Builder: `combustion.model: none` und `evaporation.model: none` werden robust verarbeitet
- Topologie: `environment`-Volumina mit festen ZustÃ¤nden `pressure_Pa` / `temperature_K` und `orifice`-Verbindungen als Drosselpfad
- WandwÃ¤rme: komplette Wall-Heat-Logik in `src/thermo0d/physics/heat_transfer.py` zentralisiert; `rhs.py` und `output/rows.py` nutzen jetzt denselben Helper fÃ¼r den Woschni-Pfad


### Zusatzupdate vom 03.04.2026 â€“ Free-Piston Phase A.2

Dieses Archiv enthÃ¤lt jetzt zusÃ¤tzlich den **minimal lauffÃ¤higen Free-Piston-RHS fÃ¼r Phase A.2**.

Neu in A.2:
- eigener Free-Piston-RHS in `src/thermo0d/model/free_piston/rhs.py`
- numerisch lauffÃ¤hige Integration von **Zylindermasse `m`, innerer Energie `U`, Kolbenposition `x` und Kolbengeschwindigkeit `v`**
- freie Geometrie Ã¼ber `cylinder_volume_from_position(...)` und `cylinder_dvdt_from_velocity(...)`
- Minimalthermodynamik in `src/thermo0d/model/free_piston/thermo.py`
- Free-Piston-Solverpfad in `src/thermo0d/model/free_piston/simulator.py`
- zeitbasierte Minimal-Postprocessing-Ausgabe fÃ¼r Free Piston ohne Winkel-/Zyklusrekonstruktion
- RHS-Hotpath bleibt **frei von Dict-Zugriffen**; der Rechenkern arbeitet nur mit Arrays, Skalarwerten und den strukturierten Bundle-Feldern, damit der Pfad in derselben Richtung **numba-kompatibel** bleibt wie das klassische/conventional Modell

A.2 verwendet im aktuellen Archiv die bereits vorhandenen Free-Piston-KonfigurationsblÃ¶cke:
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
- winkelgefÃ¼hrte Ventilprofile
- klassisches theta-/cycle-basiertes Reporting fÃ¼r den Free-Piston-Zweig

### Wesentliche Ã„nderungen dieses Stands
- `run_simulation.py` mit auswÃ¤hlbaren `simulated_args`-Presets, `project_A156A1` als Default
- Konfigurations-Versionierung mit echter Schema-Migration und RÃ¼ckwÃ¤rtskompatibilitÃ¤t
- formatierte Pydantic-, YAML- und Dateifehler in Loader und CLI
- projektweite Vordergrund-Dialoge Ã¼ber `src/thermo0d/gui/dialogs.py`
- robuster Alias-Editor mit Fehlerdialogen, exakten Dateipfaden und optionalem Start ohne Auto-Generierung
- PlotStyleEditor mit Y-Limits, Y-Min/Y-Max, Major/Minor-Step, Major/Minor-Grid, stabiler Inspector-Auswahl, echter Treffer-Markierung im Signalfilter und Subplot-DnD zwischen Figures
- ergonomische Plot-Editor-Erweiterungen: Achsenstil kopieren/einfÃ¼gen, auf Subplot oder alle Subplots anwenden, intelligente Auto-Limits aus Preview-Daten
- Startbedingungen bevorzugt Ã¼ber `initial_pressure_Pa` und `initial_temperature_K`, `initial_mass_kg` nur als Fallback
- Config-Kern weiter bereinigt: zusÃ¤tzliche BereichsprÃ¼fungen, schema-sichere Normalisierung und Master-Referenz-Config
- neues `scripts/config_tool.py` fÃ¼r `validate`, `upgrade`, `normalize`, `explain` und `diff`
- automatischer Last-Cycle-Checkreport als CSV, Konsolenreport und optional HTML
- fallklassenabhÃ¤ngige Ampelbewertung des Checkreports fÃ¼r geschlossene FÃ¤lle, Coldflow-Gaswechsel sowie gezÃ¼ndete 2T/4T-FÃ¤lle
- bereinigtes Archiv inkl. `doc/index.html`, `doc/app.js`, `doc/data.js` und `Projekte/data/`
- Hotfix fÃ¼r konsolidierte Pakete: `migrate_config_data(...)` und `migrate_yaml_text(...)` werden wieder exportiert
- RHS-Hot-Path bereinigt: zusammengefasste Zylinder-Kinematik, direkter WandwÃ¤rme-Kontext und weniger doppelte FlÃ¤chen-/Trigonometrie-Auswertung
- PlotStyleEditor und Plot-Layout nutzen bei theta-basierten CSV-Previews im Datenmodus jetzt den **realen X-Datenbereich** statt hart auf `0â€¦360/720Â°` zu klemmen; ein letzter Wert `719` bleibt damit auch visuell bei `719` ohne kÃ¼nstliche Strecke zum Ursprung
- `run.log` enthÃ¤lt jetzt zusÃ¤tzlich zur letzten Zyklusdauer auch die **gesamte Simulationslaufzeit** als `simulation_wall_clock_s`
- CSV-Export ergÃ¤nzt pro Zylinder die Spalten `<cyl>_heat_transfer_power_W` und `<cyl>_htc_W_per_m2K`; die bestehende Spalte `<cyl>_wall_heat_W` bleibt aus KompatibilitÃ¤tsgrÃ¼nden erhalten

## Zusatzupdate vom 01.04.2026

Dieses Patch-Update zieht den **RHS-Hot-Path** in `src/thermo0d/physics/rhs.py` nach und aktualisiert die Dokumentation auf denselben Stand.

Neu in diesem Patch:
- RHS intern klar in **Zustandsrekonstruktion**, **VerbindungsstrÃ¶mung** und **lokale Energieterme** gegliedert
- neue Hot-Path-Hilfe `cylinder_kinematic_state_from_time(...)` in `src/thermo0d/physics/kinematics.py`, damit Volumen, `dV/dt`, Kurbelwinkel, Kolbenweg und Winkelgeschwindigkeit pro Zylinder nur noch **einmal** berechnet werden
- WandwÃ¤rme im RHS direkt Ã¼ber `wall_heat_rate_from_row(...)` mit bereits rekonstruiertem Zylinderkontext, statt den Kontext im heiÃŸen Pfad erneut aus `vol_row` und `kin_matrix` abzuleiten
- Verbindungsquerschnitte im RHS Ã¼ber einen gemeinsamen Helper `_connection_area_and_coefficients(...)` zusammengefÃ¼hrt
- `_evaluate_valve_area(...)` entschlackt: keine unnÃ¶tige doppelte RÃ¼ckrechnung Ã¼ber `_evaluate_valve_state(...)` mehr
- analytischer Flow-Jacobian nutzt denselben zusammengefassten Zylinder-Kinematikpfad fÃ¼r bessere Konsistenz und weniger doppelte Trigonometrie

Ergebnis:
- bessere Lesbarkeit des Rechenkerns
- weniger verstreute Speziallogik im RHS
- geringerer Overhead pro RHS-Aufruf, vor allem bei mehreren Zylindern und vielen inneren Integrationsschritten

ZusÃ¤tzliche NachzÃ¼ge in diesem Stand:
- Preview- und Auto-Plot-Achsen fÃ¼r theta-basierte CSV-Daten skalieren im Datenmodus jetzt bis zum **letzten real vorhandenen X-Wert**
- `ResultRowBuilder` nutzt fÃ¼r Zylinder den zusammengefassten Kinematikpfad `cylinder_kinematic_state_from_time(...)` statt Volumen, Kolbenweg und Winkelgeschwindigkeit separat zu berechnen
- WandwÃ¤rme-CSV-Spalten werden mit einem gemeinsamen Helper fÃ¼r **WÃ¤rmeleistung und HTC** aufgebaut, damit die Woschni-ZwischengrÃ¶ÃŸe nicht doppelt hergeleitet werden muss
- `run.log` enthÃ¤lt zusÃ¤tzlich `simulation_wall_clock_s` fÃ¼r die gesamte Simulationsdauer des aktuellen Laufs


## Woschni-Varianten / WandwÃ¤rme

Das WandwÃ¤rmemodell `wall_heat.model: woschni` unterstÃ¼tzt jetzt mehrere Untervarianten:
- `variant: legacy` â€“ bisheriges Projektmodell mit den Legacy-Koeffizienten `c1/c2/c3`
- `variant: promo` â€“ Quellen-/Legacy-Modell aus dem historischen Code (`WoschniPromo`)
- `variant: classic` â€“ klassische Woschni-Variante
- `variant: swirl` â€“ klassische Woschni-Variante mit `swirl_number`
- `variant: gt` â€“ GT-nahe WoschniGT-Variante
- `variant: huber` â€“ Huber-Variante mit zusÃ¤tzlicher IMEP-/Volumenkorrektur

Neue Konfigurationsfelder unter `wall_heat:`:
- `variant`
- `multiplier`
- `cucm`
- `swirl_number`
- `imep_bar`
- `dp_mode`
- `reference_state_mode`
- `phase_mode`
- `c1/c2/c3` bleiben fÃ¼r `variant: legacy` erhalten

Praktische Empfehlung:
- fÃ¼r quellennahe LÃ¤ufe `variant: promo` verwenden
- zunÃ¤chst `dp_mode: off` beibehalten
- danach `multiplier`, `cucm`, `swirl_number` oder `imep_bar` kalibrieren

Eine kommentierte Beispielkonfiguration liegt unter:
- `examples/config_woschni_variants_documented.yaml`

## Architektur

Die Codebasis trennt strikt zwischen:
- **Input**: Laden, Validieren, AuflÃ¶sen von Pfaden, Aufbau kompakter Simulationsdaten
- **Compute**: Solver, Integrationslauf, Kennwerte
- **Output**: Sampling, Zeilenaufbau, CSV-/Excel-Export, Konsolenreporting
- **App/GUI**: Orchestrierung, Editoren, Werkzeuge

Der physikalische Rechenkern ist damit von YAML-Dateien, Exportformaten und GUI-Code getrennt.


## Freikolben / Phase A

Der Umbauplan fÃ¼r den Freikolbenpfad wurde in **Phase A** auf die Codebasis angewendet. Der Stand ist bewusst architekturorientiert und trennt den neuen Pfad sauber vom bestehenden Kurbeltrieb-Modell.

Enthalten in diesem Patch:
- neues Top-Level-Feld `modeling.architecture` mit den Werten `classic` und `free_piston`
- neue Top-Level-Sektion `free_piston` fÃ¼r Startbedingungen und mechanische Metadaten
- eigener Builder-Zweig fÃ¼r `free_piston`
- generisches `StateLayout`, damit zusÃ¤tzliche ZustÃ¤nde nicht mehr implizit auf `2 * n_vol` fest verdrahtet sind
- neue ZustÃ¤nde `free_piston_x_m` und `free_piston_v_m_per_s` im Bundle / Zustandsvektor
- eigener Modellbaum `src/thermo0d/model/` mit `conventional/` fÃ¼r den klassischen Kurbeltrieb und `free_piston/` fÃ¼r den neuen Freikolbenpfad

Wichtig:
- Der **bestehende Solverpfad fÃ¼r klassische FÃ¤lle bleibt unverÃ¤ndert**.
- Der neue Freikolbenpfad ist in Phase A **absichtlich noch nicht ausfÃ¼hrbar**. Ein Run mit `modeling.architecture: free_piston` wird deshalb mit einer klaren Meldung abgebrochen, statt unvollstÃ¤ndige oder irrefÃ¼hrende Physik zu rechnen.
- Phase B ist der nÃ¤chste Schritt fÃ¼r translatorische Mechanik, Volumen `V(x)`, KrÃ¤fte und RHS.

Beispiel fÃ¼r den neuen Architekturumschalter:

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

ZusÃ¤tzlich wurden unter `Projekte/variants/` drei neue 2-Takt-Varianten auf Basis von `Projekte/A156A1-2V-REX-V09d_WH02-Vibe_PP_RK45.yaml` abgelegt:
- `A156A1-2T-VLV-Vibe_PP_RK45.yaml` â€“ 2T mit Ventilsteuerung
- `A156A1-2T-SLTang-Vibe_PP_RK45.yaml` â€“ 2T mit schlitzgesteuerter, winkelabhÃ¤ngiger Ã–ffnung
- `A156A1-2T-SLTpos-Vibe_PP_RK45.yaml` â€“ 2T mit schlitzgesteuerter, kolbenpositionsabhÃ¤ngiger Ã–ffnung

Hinweis: Die neuen Varianten Ã¼bernehmen die bestehende A156A1-Basisstruktur, stellen aber die referenzierten Ventil-/AlphaK-Dateien auf die im Archiv tatsÃ¤chlich vorhandenen generischen `data/*.csv`-Dateien um, damit die Varianten unmittelbar auflÃ¶sbar und baubar bleiben.

## Paketstruktur

```text
src/thermo0d/
â”œâ”€ app/
â”œâ”€ compute/
â”œâ”€ config/
â”œâ”€ core/
â”œâ”€ gui/
â”œâ”€ input/
â”œâ”€ model/
â”‚  â”œâ”€ conventional/
â”‚  â””â”€ free_piston/
â”œâ”€ output/
â”œâ”€ physics/
â”œâ”€ config_versioning.py
â”œâ”€ main.py
â””â”€ version.py
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
  - Verbindungsfluss: Ventil/Slot/Orifice Ã¼ber gemeinsamen FlÃ¤chen-Helper
  - lokale Energieterme: `p*dV`, WandwÃ¤rme, Vibe, Evaporation

### Output
- `thermo0d.output.sampling.OutputSampler`
- `thermo0d.output.rows.ResultRowBuilder`
- `thermo0d.output.exporters.CsvExporter` / `ExcelExporter`
- `thermo0d.output.console.ConsoleCycleReporter`
- `thermo0d.output.service.PostprocessingService`

## `run_simulation.py`

Das Skript unterstÃ¼tzt echte CLI-Argumente oder vordefinierte Presets Ã¼ber `simulated_args`.

Verhalten:
- mit CLI-Argumenten: normale AusfÃ¼hrung
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
- bei BestÃ¤tigung erfolgt eine **echte inhaltliche Migration**, nicht nur ein Versionsstempel
- `ConfigLoader` migriert Ã¤ltere Konfigurationen zusÃ¤tzlich auch beim normalen Laden im Speicher

Beispiele fÃ¼r automatisch migrierte Felder:
- `csv_sep` / `csv_delimiter` â†’ `csv_separator`
- `simulation.solver.method` â†’ `kind`
- `sampling.mode: angle` â†’ `crank_angle`
- `step_ca_deg` â†’ `step_deg`
- `alphak_file` â†’ `alpha_k_file`
- `forward_discharge_coefficient` / `reverse_discharge_coefficient` â†’ `forward_cd` / `reverse_cd`

## Startbedingungen

Neue Konfigurationen sollen bevorzugt diese Felder verwenden:

```yaml
initial_pressure_Pa: 101325.0
initial_temperature_K: 300.0
```

Ã„ltere Dateien mit `initial_mass_kg` bleiben lesbar und werden als Fallback unterstÃ¼tzt.

## Ausgabe / Sampling

`postprocessing.sampling` unterstÃ¼tzt:
- `time` mit `step_s`
- `crank_angle` mit `step_deg`

Optional kann zusÃ¤tzlich ein letzter Arbeitszyklus auf festem Winkelraster exportiert werden:

```yaml
postprocessing:
  final_cycle_uniform_angle_export:
    enabled: true
    step_deg: 1.0
```

Dabei gilt bewusst:
- 2T: `0â€¦359Â°`
- 4T: `0â€¦719Â°`

so dass kumulierte GrÃ¶ÃŸen am Dateiende nicht auf den Zyklusursprung zurÃ¼ckspringen.

FÃ¼r Zylinder exportiert die CSV zusÃ¤tzlich zu den bisherigen BilanzgrÃ¶ÃŸen jetzt auch:
- `<cyl>_heat_transfer_power_W` als klare Alias-Spalte fÃ¼r die Zylinder-WÃ¤rmeleistung
- `<cyl>_htc_W_per_m2K` als momentanen Heat-Transfer-Coefficient der WandwÃ¤rme-Korrelation


## Ergebnis-Checkreport fÃ¼r den letzten Zyklus

Ãœber `postprocessing.check_report` kann zusÃ¤tzlich zum normalen CSV-Export ein automatischer PrÃ¼fbericht fÃ¼r den letzten Zyklus geschrieben werden.

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

Der Checkreport enthÃ¤lt unter anderem:
- Punktzahl und Winkelbereich des letzten Zyklus
- `pmin`, `pmax`, `Tmin`, `Tmax`, `mmin`, `mmax`
- integrierte ZyklusgrÃ¶ÃŸen fÃ¼r Masse, Enthalpie, WandwÃ¤rme, zugefÃ¼hrte Energie, Verdampfungsenthalpie und Kolbenarbeit
- Massen- und EnergiebilanzrestgrÃ¶ÃŸen absolut und relativ
- `overall_status` als Gesamtampel
- Zylindergeometrie in mm / mmÂ² / cmÂ³: `bore_mm`, `stroke_mm`, `conrod_mm`, `bore_area_mm2`, `swept_cm3`, `clearance_cm3`
- Ventilgeometrie in mm / mmÂ²: `lift_max_mm`, `A_ref_mm2`, `A_eff_forward_max_mm2`, `A_eff_reverse_max_mm2`
- bei Slot-FÃ¤llen zusÃ¤tzlich die maximalen SlotflÃ¤chen, inkl. `A_eff_forward_max_mm2` und `A_eff_reverse_max_mm2`

Die Ampel wird nicht mehr mit einem einzigen starren Satz Grenzwerte bewertet, sondern abhÃ¤ngig von einer automatisch erkannten Fallklasse:
- `closed_or_settling`
- `coldflow_gas_exchange`
- `fired_gas_exchange_4T`
- `fired_scavenged_2T`

Damit werden geschlossene SetzfÃ¤lle strenger bewertet als durchgesetzte MotorfÃ¤lle, und gezÃ¼ndete 2T/4T-FÃ¤lle erhalten passendere Druck-, Temperatur- und Bilanzgrenzen.

ZusÃ¤tzlich gilt jetzt fÃ¼r die Lauf-Ausgabe:
- Exportartefakte (`csv`, `xlsx`, Plotdateien, Checkreport-Dateien) werden in der Konsole nur noch mit `OK`, `WARN` oder `FAILED` gemeldet.
- VollstÃ¤ndige Pfade und Verzeichnisse werden dafÃ¼r nicht mehr in die Konsole geschrieben.

## Tabellen-Loader / `alpha_k_file`

Der Loader fÃ¼r `alpha_k_file` erkennt jetzt robust, ob die Lift-Achse in mm statt m vorliegt. Die Autokonvertierung nach m greift, wenn mindestens eines davon zutrifft:
- Header-Hinweis wie `lift_mm`, `hub_mm` oder vergleichbar
- offensichtlicher Wertebereich der Liftspalte (z. B. 1 â€¦ 10 statt 0.001 â€¦ 0.010)

Dieselbe mmâ†’m-Logik wird jetzt sowohl im Simulations-Loader als auch in der GUI-/Editor-Vorschau verwendet.

## Massenstrom-Vorzeichenkonvention

Die interne StrÃ¶mungsrichtung wird topologisch pro Verbindung Ã¼ber `from_idx -> to_idx` definiert.

Daraus folgt:
- `<connection>_mdot_kg_per_s` ist **positiv** fÃ¼r StrÃ¶mung in definierter Verbindungsrichtung
- derselbe Wert ist **negativ** bei realer Gegenrichtung
- bilanziert wird mit `-mdot` auf der linken und `+mdot` auf der rechten Seite

ZusÃ¤tzlich werden exportseitig lesbare Betragssignale gebildet:
- `<cyl>_mdot_in_kg_per_s` immer positiv
- `<cyl>_mdot_out_kg_per_s` immer positiv

## Config-Workflow

### Config-Kern / Validierung
- zusÃ¤tzliche Bereichs- und KonsistenzprÃ¼fungen fÃ¼r Solver, Kinematik, Verbrennung, Verdampfung, Slots und Winkelraster
- schema-sichere Normalisierung Ã¼ber `normalize_config_data(...)`
- RÃ¼ckwÃ¤rtskompatibilitÃ¤t bleibt erhalten; Migrationen laufen weiterhin Ã¼ber `migrate_config_data(...)`

### Referenzdateien
- `examples/config_master_reference.yaml` ist die vollstÃ¤ndige aktuelle Ausgangsvorlage
- `examples/config_schema_documented.yaml` bleibt die ausfÃ¼hrlich kommentierte Dokumentationsvorlage

### Config-Tool

```bash
python scripts/config_tool.py validate  Projekte/config.yaml
python scripts/config_tool.py upgrade   Projekte/config.yaml --output Projekte/config_upgraded.yaml
python scripts/config_tool.py normalize Projekte/config.yaml --output Projekte/config_normalized.yaml
python scripts/config_tool.py explain   Projekte/config.yaml
python scripts/config_tool.py diff      Projekte/config.yaml Projekte/config_normalized.yaml
```

Kommandos:
- `validate`: gegen aktuelles Schema prÃ¼fen
- `upgrade`: alte Feldnamen / Altstrukturen migrieren
- `normalize`: kanonische Form schreiben
- `explain`: Kurzfassung oder Pfadinhalt ausgeben
- `diff`: zwei Dateien oder eine Datei gegen die kanonische Form vergleichen

## GUI-Werkzeuge

### EngineGasExchangeEditor
- Bearbeitung von `engine` und `gasexchange`
- Timing-Preview mit rechter Y-Achse fÃ¼r Kolbenweg ab UT oder Zylindervolumen
- Vordergrund-Dialoge und robuste Dateidialoge
- RÃ¼ckwÃ¤rtskompatible Konfigurationsmigration

### PlotStyleEditor
- Y-Limits, Y-Min/Y-Max, Major/Minor-Step, Major/Minor-Grid
- X-Presets: `0â€¦360`, `0â€¦720`, `-180â€¦180`, `-360â€¦360`, Auto
- Signalfilter mit Aufklappen, echter Treffer-Markierung, TrefferzÃ¤hler, erster Treffer direkt sichtbar
- stabiler Inspector ohne RÃ¼cksprung auf das erste Element
- Subplots per Drag & Drop zwischen Figures verschiebbar, mit `Strg` kopierbar, inkl. Live-Feedback
- Achsenstil kopieren/einfÃ¼gen
- Achsenstil auf aktuellen Subplot oder alle Subplots anwenden
- intelligente Auto-Limits aus den tatsÃ¤chlich verfÃ¼gbaren Preview-Daten

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

Damit funktioniert der Editor ohne die frÃ¼heren 404-Probleme auf fehlende JS-Dateien.

## Tests

`python scripts/test_runner.py` startet `pytest`, erzeugt JUnit-XML und zusÃ¤tzlich `test_cases/index.html`.

Die Tests decken unter anderem ab:
- Konfigurationsvalidierung und Fehlerformatierung
- PfadauflÃ¶sung und CLI
- Solver-Registry inkl. stiff solver
- Kinematik und Massenstrom
- Output-Sampling und letzter Zyklus
- Konfigurationsmigrationen
- Plot-Editor-Verhalten (Axis-Inspector, Signalfilter, DnD)

## Archivbereinigung

Aus dem ausgelieferten Archiv entfernt bzw. nicht mehr Bestandteil des konsolidierten Stands:
- lose Wrapper-/Legacy-Dateien
- `*_orig` / `*.orig`
- nicht benÃ¶tigte Cache-/Build-Reste
- generierte `test_cases`-Work-Verzeichnisse, Laufartefakte und Plot-Dateien
- temporÃ¤re Normalisierungs-/PrÃ¼fdateien aus ZwischenstÃ¤nden

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

## VersionsstÃ¤nde
- Package-Version: `7.1.56`
- Config-Schema-Version: `4`

## Pflegehinweis

Diese `README.md` beschreibt den konsolidierten Ist-Stand dieses ZIP-Archivs und wird bei Ã„nderungen am ausgelieferten Paket mitgefÃ¼hrt.


## Umgebung und Drossel in der Topologie

ZusÃ¤tzlich zu `cylinder` und `plenum` unterstÃ¼tzt die Topologie jetzt den Volumentyp `environment` als feste Randbedingung mit konstantem Druck und konstanter Temperatur. FÃ¼r Verbindungen ist der Typ `orifice` als stationÃ¤re Drossel verfÃ¼gbar.

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
- `environment` ist eine feste Randbedingung. `pressure_Pa` und `temperature_K` bleiben wÃ¤hrend der Simulation konstant.
- `orifice` verwendet die isentrope Drosselgleichung mit separaten `forward_cd`- und `reverse_cd`-Werten.
- `environment` kann direkt im Topologie-Editor angelegt werden; `orifice` ist dort als Drossel verfÃ¼gbar.


## Postprocessing: Plot-Ausgabe, Layout-Dateien und Konsolen-Schalter

Der Root-Block `postprocessing` unterstÃ¼tzt jetzt zusÃ¤tzlich konfigurierbare Plot- und Konsolenausgabe:

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
- `postprocessing.plots.source` wÃ¤hlt die Datenbasis fÃ¼r Standardplots und Layout-Rendering:
  - `last_cycle_uniform`: letzter Zyklus auf festem Winkelraster
  - `export_rows`: normale Exporttabelle
- `postprocessing.plots.output_dir` setzt optional einen Zielordner fÃ¼r mit `plot.yaml`-Layouts erzeugte Grafiken.
- `postprocessing.plots.pressure_plot.*` steuert den einfachen Standard-Druckplot separat.
- `postprocessing.plots.layouts.auto_create_defaults` erzeugt bei Bedarf `plot.yaml` und `plot10.yaml`, falls keine EintrÃ¤ge angegeben sind.
- `postprocessing.plots.layouts.entries` ist eine Liste externer Plot-Layout-Dateien mit optionalem PrÃ¤fix.
- `postprocessing.console.*` schaltet die Konsolenabschnitte fÃ¼r Run-Summary, Cycle-Summary, Checkreport und Geometrie getrennt.

### Editoren und Migration

Die neuen Felder sind integriert in:
- Pydantic-Config-Modelle (`src/thermo0d/config/models.py`)
- Config-Migration (`src/thermo0d/config_versioning.py`)
- Schema-/Hint-Metadaten (`src/thermo0d/config/schema_meta.py`)
- Topology-Config-Editor (`src/thermo0d/gui/topology_config_editor.py`)
- Runner-Orchestrierung (`src/thermo0d/app/runner.py`)

Im Topology-Editor ist `postprocessing.plots.layouts.entries` als YAML-Mehrzeilenfeld editierbar.

## Konsolenstatus und Timing

Der Lauf gibt jetzt zusÃ¤tzlich Status- und Timingzeilen fÃ¼r die wichtigsten Schritte aus:

- `[run] wall_clock_s=... solver=...` misst den AusfÃ¼hrungsteil im `SimulationExecutor`
- `[analysis:cycle-index]`, `[analysis:cycle-summary]` messen die Analyse direkt nach dem Solver
- `[postprocessing:*]` zeigen Filterung, Sampling, Rekonstruktion, Integrale und Gesamtzeit
- `[csv]`, `[xlsx]`, `[csv:last-cycle-uniform]`, `[csv:check-report]`, `[html:check-report]` zeigen Status plus Laufzeit
- `[plot]`, `[plot.yaml]`, `[plot10.yaml]` zeigen Status plus Laufzeit der Plot-Erzeugung

Die frÃ¼here Gesamtliste aller Zyklen am Ende wird nicht mehr zusÃ¤tzlich ausgegeben. Bei SciPy-Solvern bleiben die Live-Zykluszeilen wÃ¤hrend der Integration erhalten.

## Ablageort fÃ¼r `plot.yaml`-Dateien

Layout-Dateien aus `postprocessing.plots.layouts.entries[].path` werden relativ zur verwendeten YAML-Konfigurationsdatei aufgelÃ¶st.

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


### VollstÃ¤ndiges Beispiel

Eine vollstÃ¤ndige Beispielkonfiguration auf Basis des A156A1-2V-REX-WH02-Vibe-Falls mit allen Postprocessing-Optionen liegt unter:

- `examples/A156A1-2V-REX-V09d_WH02-Vibe_postprocessing_full.yaml`

## Output-Verzeichnis

Simulationsergebnisse werden zentral in ein Laufverzeichnis unterhalb von `results/` geschrieben.

- Standard: Name der verwendeten Konfigurationsdatei ohne Extension, auf 15 Zeichen gekÃ¼rzt
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
- `postprocessing.outdir` Ã¼berschreibt den Basisnamen, bleibt aber ebenfalls auf 15 Zeichen begrenzt und kollisionssicher.
- CSV/XLSX/Check-Report/Last-Cycle-CSV landen unter `results/<kurzname>/results/`.
- Plotbilder landen unter `results/<kurzname>/plots/`.
- `run.log` und `fail.log` bleiben zentral unter `test_cases/`.

---

## Quelle: README_INJECTOR_STAGE1.md

Zeitstempel: `2026-04-21 15:36:20`

# Injector Stage 1 Patch

Dieser Patch setzt die erste Etappe fÃ¼r den Free-Piston-Injektorpfad um.

## Enthalten

- neuer `fueling_mode`:
  - `lambda_from_cylinder_air_at_slot_close_vapor_injector`
- neue Config-Felder in `combustion`:
  - `injection_duration_s`
  - `injection_duration_ms`
- Free-Piston-Runtime-Felder fÃ¼r einen Vapor-Injektor
- Slot-Close-Latch bestimmt aus der **gelatchten Luftmasse** die Ziel-Kraftstoffmasse
- Injektor speist diese Masse Ã¼ber die Einspritzdauer direkt in `m_fuel_vapor` bzw. den Gaszustand ein

## Wichtig

Dies ist bewusst nur **Etappe 1**:

- der Injektorpfad ist vorhanden
- die Ziel-Kraftstoffmasse wird aus `lambda_target` und gelatchter Zylinder-Luftmasse berechnet
- der Kraftstoff wird direkt als Dampfmasse in den Zylinder eingespeist

Die Verbrennung ist in diesem Patch **noch nicht vollstÃ¤ndig auf expliziten Verbrauch von `m_fuel_vapor` und `m_air` umgebaut**. Das ist der nÃ¤chste Schritt.

## Beispiel

```yaml
combustion:
  model: vibe
  fueling_mode: lambda_from_cylinder_air_at_slot_close_vapor_injector
  lambda_target: 1.0
  injection_duration_ms: 0.5
  lhv_J_per_kg: 43000000.0
  afr_stoich_kg_air_per_kg_fuel: 14.5
  combustion_efficiency_0to1: 0.98
```

---

## Quelle: README_INJECTOR_STAGE2_COMBUSTION_BALANCE.md

Zeitstempel: `2026-04-21 15:36:20`

This patch is intended as the next step after:
1) Phase 1 / Phase 2 combined patch
2) injector_stage1_code_patch

What it changes:
- free-piston combustion now performs explicit mass reshuffling based on actual available cylinder fuel vapor and air
- requested heat release is converted to a requested fuel burn rate via qdot/(LHV*eta)
- actual fuel burn rate is limited by:
  - available fuel vapor mass
  - available air mass / AFR_stoich
- air mass is reduced explicitly
- burned mass is increased explicitly
- total gas mass remains unchanged during combustion
- effective qdot is reduced accordingly when fuel/air availability limits combustion

New runtime diagnostics exported in free-piston rows:
- cylinder_combustion_fuel_burn_rate_kg_per_s
- cylinder_combustion_air_consumption_rate_kg_per_s
- cylinder_combustion_burned_production_rate_kg_per_s
- cylinder_combustion_qdot_effective_W

Checked on a composed workspace (base archive + phase1/phase2 + injector stage1):
- compileall successful
- free_piston_GenSet_V09f.yaml with fueling_mode=lambda_from_cylinder_air_at_slot_close_vapor_injector builds successfully
- RHS smoke test returns finite values

---

## Quelle: README_plot.md

Zeitstempel: `2026-04-21 15:36:20`

# README_plot.md

Diese Datei beschreibt die Plot-Konfiguration fÃ¼r den aktuellen Stand von `thermo0d`.

## Neu in diesem Stand

ZusÃ¤tzlich zu den bisherigen Plot-Parametern sind jetzt diese Optionen verfÃ¼gbar:

### Stil / globale Darstellung (`style`)

```yaml
style:
  preset_name: Light Engineering
  background_color: "#ffffff"
  axes_facecolor: "#ffffff"
  text_color: "#202020"
  grid_color: "#d8d8d8"
  legend_facecolor: "#ffffff"
  legend_edgecolor: "#9aa0a6"
  default_line_width: 1.8
  default_marker_size: 4.5
  font_family: DejaVu Sans
  font_size: 10
  axis_label_size: 10
  tick_label_size: 10
  title_size: 12
  figure_title_size: 14
  subplot_title_visible: true
  figure_title_visible: true
  grid_visible: true
  grid_alpha: 0.65
  legend_visible: true
  legend_position: best
  tight_layout: true
```

Wichtig:
- `axis_label_size`: SchriftgrÃ¶ÃŸe fÃ¼r X- und Y-Achsenbeschriftungen
- `tick_label_size`: SchriftgrÃ¶ÃŸe fÃ¼r Tick-Labels
- `title_size`: SchriftgrÃ¶ÃŸe fÃ¼r Subplot-Titel
- `figure_title_size`: SchriftgrÃ¶ÃŸe fÃ¼r den Figure-Gesamttitel
- `subplot_title_visible`: globale Freigabe fÃ¼r Subplot-Titel
- `figure_title_visible`: globale Freigabe fÃ¼r Figure-Titel

### Neue Subplot-Optionen

```yaml
subplots:
  - title: Zylinderdruck Ã¼ber Zeit
    show_title: true
    x_signal: t_s
    x_title: Zeit [s]
    x_limit_mode: data
    x_min: 0.0
    x_max: 1.0
    x_start_at_zero: true
```

Wichtig:
- `show_title`: blendet den Titel dieses Subplots ein oder aus
- `x_start_at_zero`: wenn `x_limit_mode: data`, startet die X-Achse bei 0

## WÃ¤hlbare Stil-Presets

Im Plot-Editor sind jetzt diese Presets auswÃ¤hlbar:

- `Light Engineering`
- `Compact Engineering`
- `Paper`
- `Dark Engineering`
- `Dark Presentation`
- `Presentation`

Empfehlung:
- **Light Engineering**: guter Standard fÃ¼r Entwicklung
- **Compact Engineering**: kompakter fÃ¼r viele Subplots
- **Paper**: sachlich, wenig Ballast, Titel standardmÃ¤ÃŸig aus
- **Presentation**: grÃ¶ÃŸere Linien und Schriften
- **Dark Engineering / Dark Presentation**: dunkle OberflÃ¤che

## Alle wichtigen Felder

### Root-Ebene

```yaml
name: Mein Plotprojekt
figures: []
style: {}
config_path: ""
signals_path: ""
preview_csv_path: ""
selected_cylinder: user_cylinder_1
notes: ""
```

### Figure

```yaml
figures:
  - title: Figure 1
    rows: 2
    cols: 1
    subplots: []
```

### Subplot

```yaml
subplots:
  - title: Druck
    show_title: true
    plot_type: line
    x_signal: theta_deg
    x_title: Kurbelwinkel [deg]
    x_unit_preset: deg
    x_scale_factor: 1.0
    x_offset: 0.0
    x_limit_mode: data    # data | manual
    x_min: 0.0
    x_max: 720.0
    x_start_at_zero: true
    legend_visible: true
    legend_position: best
    show_grid: true
    y_axes: []
    series: []
    events: []
    y_lines: []
```

### Y-Achse

```yaml
y_axes:
  - id: ax_p
    title: Druck [bar]
    side: left            # left | right
    spine_offset: 0.0
    color: "#111111"
    visible: true
    limit_mode: data      # data | manual
    y_min: 0.0
    y_max: 100.0
    tick_step: 10.0
    minor_tick_step: 5.0
    major_grid: true
    minor_grid: false
```

### Serie

```yaml
series:
  - signal_key: cylinder_p_Pa
    label: Zylinderdruck
    axis_id: ax_p
    visible: true
    color: "#111111"
    line_style: "-"
    marker: ""
    line_width: 1.8
    marker_size: 4.5
    unit_preset: bar
    scale_factor: 1.0
    offset: 0.0
    series_type: line     # line | scatter | step
```

### Ereignisse (`events`)

```yaml
events:
  - x: 360.0
    label: OT
    color: "#666666"
    line_style: ":"
    line_width: 1.0
    alpha: 0.9
    visible: true
    show_label: true
    event_type: reference
    label_rotation: 90.0
    label_font_size: 7.0
    label_bg_color: "#ffffff"
    label_bg_alpha: 0.8
    label_border_color: none
    label_y: 0.98
    label_ha: right
    label_va: top
```

### Horizontale Linien (`y_lines`)

```yaml
y_lines:
  - y: 54.0
    axis_id: ax_p
    label: Grenze
    color: "#667085"
    line_style: "--"
    line_width: 1.0
    alpha: 0.9
    visible: true
    show_label: true
    label_x: 0.99
    label_position: above   # above | below | center
    label_offset_pt: 3.0
    label_ha: right
    label_va: bottom
    label_font_size: 8.0
    label_bg_color: "#ffffff"
    label_bg_alpha: 0.75
    label_border_color: none
```

## Professionelle Grundeinstellung â€“ Vorschlag

FÃ¼r technische Standardplots empfehle ich:

```yaml
style:
  preset_name: Light Engineering
  axis_label_size: 11
  tick_label_size: 10
  title_size: 12
  figure_title_size: 14
  subplot_title_visible: true
  figure_title_visible: true
  grid_visible: true
  grid_alpha: 0.5
  legend_visible: true
  legend_position: best

figures:
  - title: Hauptdiagramme
    rows: 2
    cols: 1
    subplots:
      - title: Druckverlauf
        show_title: true
        x_signal: t_s
        x_title: Zeit [s]
        x_limit_mode: data
        x_start_at_zero: true
        show_grid: true
        legend_visible: true
```

## FÃ¼r Berichte / Paper

```yaml
style:
  preset_name: Paper
  subplot_title_visible: false
  figure_title_visible: false
  axis_label_size: 10
  tick_label_size: 9
  grid_alpha: 0.45
```

## FÃ¼r PrÃ¤sentation

```yaml
style:
  preset_name: Presentation
  axis_label_size: 12
  tick_label_size: 11
  title_size: 15
  figure_title_size: 17
```

## Hinweis zum aktuellen Renderer

Die neuen Felder werden jetzt sowohl im Plot-Editor als auch im Batch-Renderer berÃ¼cksichtigt fÃ¼r:

- X-Achse ab 0 im Auto-Modus
- AchsenbeschriftungsgrÃ¶ÃŸe
- Tick-Label-GrÃ¶ÃŸe
- Subplot-Titel ein/aus
- Figure-Titel ein/aus
- Figure-/Subplot-TitelgrÃ¶ÃŸen
- Stil-Presets

---

## Quelle: README_quellen_step1.md

Zeitstempel: `2026-04-21 15:36:20`

# Quellen-Archiv Schritt 1

Umgesetzt ist ein erster Stoffwert-Zwischenschritt im Stil des Quellen-Archivs:

- neue Stoffwertkorrelation `src/thermo0d/physics/quellen_props.py`
- `R(lambda)`, `cv(lambda,T)`, `cp=cv+R`, `gamma=cp/cv`
- Temperatur aus `m,U,lambda` iterativ wie im Quellen-Ansatz
- variable Stoffwerte im klassischen RHS und im Free-Piston-RHS
- Upstream-`gamma`, `R`, `cp` fÃ¼r Massestrom und Enthalpiestrom
- Builder speichern je Volumen optionale Brennstoffmasse und stÃ¶chiometrisches AFR
- initiale innere Energie wird mit dem neuen `cv(lambda,T)` neu gesetzt
- Rekonstruktion/Postprocessing geben zusÃ¤tzliche Stoffwertsignale aus

## Wichtige EinschrÃ¤nkungen

- `lambda` wird nur dort physikalisch sinnvoll, wo echte `fuel_mass_per_cycle_kg` oder beim Free-Piston eine gelatchte Brennstoffmasse vorliegt.
- Konfigurationen mit nur `added_energy_per_cycle_J` ohne echte Brennstoffmasse fallen auf ein luftÃ¤hnliches Verhalten zurÃ¼ck.
- Das ist bewusst ein Zwischenschritt vor einem echten zusammensetzungsbasierten Modell.

## GeÃ¤nderte Dateien

- `src/thermo0d/physics/quellen_props.py`
- `src/thermo0d/physics/rhs.py`
- `src/thermo0d/model/free_piston/rhs.py`
- `src/thermo0d/model/conventional/builder.py`
- `src/thermo0d/model/free_piston/builder.py`
- `src/thermo0d/core/model_bundle.py`
- `src/thermo0d/output/reconstruction.py`
- `src/thermo0d/model/free_piston/postprocessing.py`

---

## Quelle: README_updated - Kopie.md

Zeitstempel: `2026-04-21 15:36:20`

# thermo0d v0.4

## Konsolidierter Stand vom 01.04.2026

Dieses Archiv enthÃ¤lt den konsolidierten Gesamtstand eines datengetriebenen 0D-Kreisprozess-Frameworks mit klarer Trennung von Eingabe, Rechenkern, Ausgabe und GUI-Werkzeugen.

Der aktuelle Stand enthÃ¤lt zusÃ¤tzlich die zuletzt nachgezogenen Physik- und Auswerte-Hotfixes fÃ¼r:
- zentrale Auslagerung lokaler Energieterme aus `rhs.py`
- saubere Trennung von WandwÃ¤rme, Verbrennung und Evaporation in eigene Physik-Module
- korrigierte `angle_reference`-Logik fÃ¼r `absolute`, `compression_tdc` und `gas_exchange_tdc`
- Wrap-Logik fÃ¼r zyklusÃ¼bergreifende Fenster von Verbrennung und Evaporation
- konsistente Nutzung derselben Source-Term-Logik in Solver, Export und Plot-Auswertung

Enthalten sind auÃŸerdem die bereits zuvor nachgezogenen Konsolidierungs-Hotfixes:
- Topology-Editor: fehlende `schema_meta`-Imports behoben (`meta_for`, `SOLVER_KINDS`, `SAMPLING_MODES`, `ANGLE_REFERENCES`, `PROFILE_ANGLE_DOMAINS`)
- Topology-Editor: deaktivierte Teilmodelle werden beim Speichern bereinigt und rÃ¼ckwÃ¤rtskompatibel geladen
- Matrix-Builder: `combustion.model: none` und `evaporation.model: none` werden robust verarbeitet
- Topologie: `environment`-Volumina mit festen ZustÃ¤nden `pressure_Pa` / `temperature_K` und `orifice`-Verbindungen als Drosselpfad
- Loader/GUI: robuste mmâ†’m-Erkennung fÃ¼r `alpha_k_file`
- WandwÃ¤rme: einheitlicher Woschni-Pfad fÃ¼r Solver und Export

## Wesentliche Ã„nderungen dieses Stands

- `run_simulation.py` mit auswÃ¤hlbaren `simulated_args`-Presets, `project_A156A1` als Default
- Konfigurations-Versionierung mit echter Schema-Migration und RÃ¼ckwÃ¤rtskompatibilitÃ¤t
- formatierte Pydantic-, YAML- und Dateifehler in Loader und CLI
- projektweite Vordergrund-Dialoge Ã¼ber `src/thermo0d/gui/dialogs.py`
- robuster Alias-Editor mit Fehlerdialogen, exakten Dateipfaden und optionalem Start ohne Auto-Generierung
- PlotStyleEditor mit Y-Limits, Y-Min/Y-Max, Major/Minor-Step, Major/Minor-Grid, stabiler Inspector-Auswahl, echter Treffer-Markierung im Signalfilter und Subplot-DnD zwischen Figures
- ergonomische Plot-Editor-Erweiterungen: Achsenstil kopieren/einfÃ¼gen, auf Subplot oder alle Subplots anwenden, intelligente Auto-Limits aus Preview-Daten
- Startbedingungen bevorzugt Ã¼ber `initial_pressure_Pa` und `initial_temperature_K`, `initial_mass_kg` nur als Fallback
- Config-Kern weiter bereinigt: zusÃ¤tzliche BereichsprÃ¼fungen, schema-sichere Normalisierung und Master-Referenz-Config
- neues `scripts/config_tool.py` fÃ¼r `validate`, `upgrade`, `normalize`, `explain` und `diff`
- automatischer Last-Cycle-Checkreport als CSV, Konsolenreport und optional HTML
- fallklassenabhÃ¤ngige Ampelbewertung des Checkreports fÃ¼r geschlossene FÃ¤lle, Coldflow-Gaswechsel sowie gezÃ¼ndete 2T/4T-FÃ¤lle
- bereinigtes Archiv inkl. `doc/index.html`, `doc/app.js`, `doc/data.js` und `Projekte/data/`
- Hotfix fÃ¼r konsolidierte Pakete: `migrate_config_data(...)` und `migrate_yaml_text(...)` werden wieder exportiert

## Neu im Physikkern dieses Stands

### 1. Lokale Energieterme aus `rhs.py` ausgelagert

Die bisher in `src/thermo0d/physics/rhs.py` eingebetteten Modelle fÃ¼r Verbrennung und Evaporation wurden in eigene Module ausgelagert:

- `src/thermo0d/physics/heat_transfer.py`
- `src/thermo0d/physics/combustion.py`
- `src/thermo0d/physics/evaporation.py`
- `src/thermo0d/physics/source_terms.py`

Damit Ã¼bernimmt `rhs.py` wieder primÃ¤r die Bilanzgleichungen und die ZusammenfÃ¼hrung der einzelnen BeitrÃ¤ge.

### 2. Gemeinsame Source-Term-Auswertung

`src/thermo0d/physics/source_terms.py` bÃ¼ndelt die lokalen Energieterme je Zylindervolumen:

- `p*dV`
- WandwÃ¤rme
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

### 4. Wrap-Logik fÃ¼r zyklusÃ¼bergreifende Fenster

Verbrennungs- und Evaporationsfenster dÃ¼rfen jetzt Ã¼ber den Zyklusursprung laufen, zum Beispiel:
- `start_deg = 350`, `duration_deg = 30` in 2T
- `start_deg = 710`, `duration_deg = 40` in 4T

Die Aktivierung und Fortschrittsberechnung dieser Fenster wird jetzt korrekt zyklisch ausgewertet.

### 5. Plot-/GUI-Seite nachgezogen

Die Winkel- und Ereignislogik wurde fÃ¼r die Darstellungsseite mitgezogen:
- `src/thermo0d/output/plot_layout.py`
- `src/thermo0d/gui/plot_style_editor.py`

Damit bleiben Eventmarker, Layout-Auswertung und Solver-Referenzierung konsistent.

## Architektur

Die Codebasis trennt strikt zwischen:
- **Input**: Laden, Validieren, AuflÃ¶sen von Pfaden, Aufbau kompakter Simulationsdaten
- **Compute**: Solver, Integrationslauf, Kennwerte
- **Physics**: Kinematik, StrÃ¶mung, lokale Quell- und Senkterme
- **Output**: Sampling, Zeilenaufbau, CSV-/Excel-Export, Konsolenreporting
- **App/GUI**: Orchestrierung, Editoren, Werkzeuge

Der physikalische Rechenkern ist damit von YAML-Dateien, Exportformaten und GUI-Code getrennt.

## Paketstruktur

```text
src/thermo0d/
â”œâ”€ app/
â”œâ”€ compute/
â”œâ”€ config/
â”œâ”€ core/
â”œâ”€ gui/
â”œâ”€ input/
â”œâ”€ output/
â”œâ”€ physics/
â”œâ”€ config_versioning.py
â”œâ”€ main.py
â””â”€ version.py
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

### WandwÃ¤rme
Die WandwÃ¤rme wird zentral Ã¼ber `src/thermo0d/physics/heat_transfer.py` ausgewertet. Der aktuelle Pfad nutzt eine vereinfachte Woschni-artige HTC-Korrelation, die in Solver und Export konsistent verwendet wird.

### Verbrennung
`src/thermo0d/physics/combustion.py` implementiert aktuell eine vorgegebene Vibe-WÃ¤rmefreisetzung als Energieterm pro Zyklusfenster.

Wichtig:
- derzeit **keine** Speziesbilanz
- derzeit **keine** Oâ‚‚-Verbrauchsrechnung
- derzeit **keine** Kopplung an eine separate flÃ¼ssige Kraftstoffmasse

### Evaporation
`src/thermo0d/physics/evaporation.py` implementiert aktuell einen vorgegebenen Evaporations-Sinkterm als EnergiekÃ¼hlung im konfigurierten Fenster.

Wichtig:
- derzeit **keine** separate FlÃ¼ssigphase
- derzeit **keine** eigene Kraftstoff-Massenbilanz
- derzeit **keine** physikalische Verdampfungsrate aus Tropfen-/Filmzustand

### RHS
`src/thermo0d/physics/rhs.py` assembliert damit im Wesentlichen:
- Massenbilanz
- EnthalpiestrÃ¶me aus Verbindungen
- `p*dV`
- WandwÃ¤rme
- Verbrennung
- Evaporation

Die Datei enthÃ¤lt weiterhin die zentrale Differentialgleichung und Jacobian-UnterstÃ¼tzung, nicht mehr aber die komplette lokale Modelllogik im Detail.

## `run_simulation.py`

Das Skript unterstÃ¼tzt echte CLI-Argumente oder vordefinierte Presets Ã¼ber `simulated_args`.

Verhalten:
- mit CLI-Argumenten: normale AusfÃ¼hrung
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
- bei BestÃ¤tigung erfolgt eine **echte inhaltliche Migration**, nicht nur ein Versionsstempel
- `ConfigLoader` migriert Ã¤ltere Konfigurationen zusÃ¤tzlich auch beim normalen Laden im Speicher

Beispiele fÃ¼r automatisch migrierte Felder:
- `csv_sep` / `csv_delimiter` â†’ `csv_separator`
- `simulation.solver.method` â†’ `kind`
- `sampling.mode: angle` â†’ `crank_angle`
- `step_ca_deg` â†’ `step_deg`
- `alphak_file` â†’ `alpha_k_file`
- `forward_discharge_coefficient` / `reverse_discharge_coefficient` â†’ `forward_cd` / `reverse_cd`

## Startbedingungen

Neue Konfigurationen sollen bevorzugt diese Felder verwenden:

```yaml
initial_pressure_Pa: 101325.0
initial_temperature_K: 300.0
```

Ã„ltere Dateien mit `initial_mass_kg` bleiben lesbar und werden als Fallback unterstÃ¼tzt.

## Ausgabe / Sampling

`postprocessing.sampling` unterstÃ¼tzt:
- `time` mit `step_s`
- `crank_angle` mit `step_deg`

Optional kann zusÃ¤tzlich ein letzter Arbeitszyklus auf festem Winkelraster exportiert werden:

```yaml
postprocessing:
  final_cycle_uniform_angle_export:
    enabled: true
    step_deg: 1.0
```

Dabei gilt bewusst:
- 2T: `0â€¦359Â°`
- 4T: `0â€¦719Â°`

so dass kumulierte GrÃ¶ÃŸen am Dateiende nicht auf den Zyklusursprung zurÃ¼ckspringen.

## Ergebnis-Checkreport fÃ¼r den letzten Zyklus

Ãœber `postprocessing.check_report` kann zusÃ¤tzlich zum normalen CSV-Export ein automatischer PrÃ¼fbericht fÃ¼r den letzten Zyklus geschrieben werden.

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

Der Checkreport enthÃ¤lt unter anderem:
- Punktzahl und Winkelbereich des letzten Zyklus
- `pmin`, `pmax`, `Tmin`, `Tmax`, `mmin`, `mmax`
- integrierte ZyklusgrÃ¶ÃŸen fÃ¼r Masse, Enthalpie, WandwÃ¤rme, zugefÃ¼hrte Energie, Verdampfungsenthalpie und Kolbenarbeit
- Massen- und EnergiebilanzrestgrÃ¶ÃŸen absolut und relativ
- `overall_status` als Gesamtampel
- Zylindergeometrie in mm / mmÂ² / cmÂ³: `bore_mm`, `stroke_mm`, `conrod_mm`, `bore_area_mm2`, `swept_cm3`, `clearance_cm3`
- Ventilgeometrie in mm / mmÂ²: `lift_max_mm`, `A_ref_mm2`, `A_eff_forward_max_mm2`, `A_eff_reverse_max_mm2`
- bei Slot-FÃ¤llen zusÃ¤tzlich die maximalen SlotflÃ¤chen, inkl. `A_eff_forward_max_mm2` und `A_eff_reverse_max_mm2`

Die Ampel wird nicht mehr mit einem einzigen starren Satz Grenzwerte bewertet, sondern abhÃ¤ngig von einer automatisch erkannten Fallklasse:
- `closed_or_settling`
- `coldflow_gas_exchange`
- `fired_gas_exchange_4T`
- `fired_scavenged_2T`

Damit werden geschlossene SetzfÃ¤lle strenger bewertet als durchgesetzte MotorfÃ¤lle, und gezÃ¼ndete 2T/4T-FÃ¤lle erhalten passendere Druck-, Temperatur- und Bilanzgrenzen.

ZusÃ¤tzlich gilt jetzt fÃ¼r die Lauf-Ausgabe:
- Exportartefakte (`csv`, `xlsx`, Plotdateien, Checkreport-Dateien) werden in der Konsole nur noch mit `OK`, `WARN` oder `FAILED` gemeldet.
- VollstÃ¤ndige Pfade und Verzeichnisse werden dafÃ¼r nicht mehr in die Konsole geschrieben.

## Tabellen-Loader / `alpha_k_file`

Der Loader fÃ¼r `alpha_k_file` erkennt jetzt robust, ob die Lift-Achse in mm statt m vorliegt. Die Autokonvertierung nach m greift, wenn mindestens eines davon zutrifft:
- Header-Hinweis wie `lift_mm`, `hub_mm` oder vergleichbar
- offensichtlicher Wertebereich der Liftspalte (z. B. 1 â€¦ 10 statt 0.001 â€¦ 0.010)

Dieselbe mmâ†’m-Logik wird jetzt sowohl im Simulations-Loader als auch in der GUI-/Editor-Vorschau verwendet.

## Massenstrom-Vorzeichenkonvention

Die interne StrÃ¶mungsrichtung wird topologisch pro Verbindung Ã¼ber `from_idx -> to_idx` definiert.

Daraus folgt:
- `<connection>_mdot_kg_per_s` ist **positiv** fÃ¼r StrÃ¶mung in definierter Verbindungsrichtung
- derselbe Wert ist **negativ** bei realer Gegenrichtung
- bilanziert wird mit `-mdot` auf der linken und `+mdot` auf der rechten Seite

ZusÃ¤tzlich werden exportseitig lesbare Betragssignale gebildet:
- `<cyl>_mdot_in_kg_per_s` immer positiv
- `<cyl>_mdot_out_kg_per_s` immer positiv

## Config-Workflow

### Config-Kern / Validierung
- zusÃ¤tzliche Bereichs- und KonsistenzprÃ¼fungen fÃ¼r Solver, Kinematik, Verbrennung, Verdampfung, Slots und Winkelraster
- schema-sichere Normalisierung Ã¼ber `normalize_config_data(...)`
- RÃ¼ckwÃ¤rtskompatibilitÃ¤t bleibt erhalten; Migrationen laufen weiterhin Ã¼ber `migrate_config_data(...)`

### Referenzdateien
- `examples/config_master_reference.yaml` ist die vollstÃ¤ndige aktuelle Ausgangsvorlage
- `examples/config_schema_documented.yaml` bleibt die ausfÃ¼hrlich kommentierte Dokumentationsvorlage

### Config-Tool

```bash
python scripts/config_tool.py validate  Projekte/config.yaml
python scripts/config_tool.py upgrade   Projekte/config.yaml --output Projekte/config_upgraded.yaml
python scripts/config_tool.py normalize Projekte/config.yaml --output Projekte/config_normalized.yaml
python scripts/config_tool.py explain   Projekte/config.yaml
python scripts/config_tool.py diff      Projekte/config.yaml Projekte/config_normalized.yaml
```

Kommandos:
- `validate`: gegen aktuelles Schema prÃ¼fen
- `upgrade`: alte Feldnamen / Altstrukturen migrieren
- `normalize`: kanonische Form schreiben
- `explain`: Kurzfassung oder Pfadinhalt ausgeben
- `diff`: zwei Dateien oder eine Datei gegen die kanonische Form vergleichen

## GUI-Werkzeuge

### EngineGasExchangeEditor
- Bearbeitung von `engine` und `gasexchange`
- Timing-Preview mit rechter Y-Achse fÃ¼r Kolbenweg ab UT oder Zylindervolumen
- Vordergrund-Dialoge und robuste Dateidialoge
- RÃ¼ckwÃ¤rtskompatible Konfigurationsmigration

### PlotStyleEditor
- Y-Limits, Y-Min/Y-Max, Major/Minor-Step, Major/Minor-Grid
- X-Presets: `0â€¦360`, `0â€¦720`, `-180â€¦180`, `-360â€¦360`, Auto
- Signalfilter mit Aufklappen, echter Treffer-Markierung, TrefferzÃ¤hler, erster Treffer direkt sichtbar
- stabiler Inspector ohne RÃ¼cksprung auf das erste Element
- Subplots per Drag & Drop zwischen Figures verschiebbar, mit `Strg` kopierbar, inkl. Live-Feedback
- Achsenstil kopieren/einfÃ¼gen
- Achsenstil auf aktuellen Subplot oder alle Subplots anwenden
- intelligente Auto-Limits aus den tatsÃ¤chlich verfÃ¼gbaren Preview-Daten
- nachgezogene Winkel-/Eventlogik passend zu `absolute` und zyklischem Wrap

### TopologyConfigEditor
- Eigenschaften-Panel mit schema-basierten Hinweisen
- Pflichtfelder werden mit `*` markiert
- Tooltips zeigen Typ, Pflichtstatus, Default und erlaubte Werte
- kompakte Kontext-Hinweise pro Root / Cylinder / Plenum / Valve / Slot

## Tests

FÃ¼r die zuletzt nachgezogenen PhysikÃ¤nderungen wurden insbesondere die folgenden Testpfade erweitert bzw. ergÃ¤nzt:
- `tests/test_rhs_helpers_extended.py`
- `tests/test_flow_kinematics_extended.py`
- `tests/test_parser_rhs.py`

Diese Tests decken insbesondere ab:
- Referenzierung mit lokalem vs. globalem Winkel
- Wrap-Fenster Ã¼ber den Zyklusursprung
- Parser-/RHS-KompatibilitÃ¤t nach der Source-Term-Auslagerung


## Postprocessing: Plot-Ausgabe, Layout-Dateien und Konsolen-Schalter

Der Root-Block `postprocessing` unterstÃ¼tzt jetzt zusÃ¤tzlich konfigurierbare Plot- und Konsolenausgabe:

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
- `postprocessing.plots.source` wÃ¤hlt die Datenbasis fÃ¼r Standardplots und Layout-Rendering:
  - `last_cycle_uniform`: letzter Zyklus auf festem Winkelraster
  - `export_rows`: normale Exporttabelle
- `postprocessing.plots.output_dir` setzt optional einen Zielordner fÃ¼r mit `plot.yaml`-Layouts erzeugte Grafiken.
- `postprocessing.plots.pressure_plot.*` steuert den einfachen Standard-Druckplot separat.
- `postprocessing.plots.layouts.auto_create_defaults` erzeugt bei Bedarf `plot.yaml` und `plot10.yaml`, falls keine EintrÃ¤ge angegeben sind.
- `postprocessing.plots.layouts.entries` ist eine Liste externer Plot-Layout-Dateien mit optionalem PrÃ¤fix.
- `postprocessing.console.*` schaltet die Konsolenabschnitte fÃ¼r Run-Summary, Cycle-Summary, Checkreport und Geometrie getrennt.

### Editoren und Migration

Die neuen Felder sind integriert in:
- Pydantic-Config-Modelle (`src/thermo0d/config/models.py`)
- Config-Migration (`src/thermo0d/config_versioning.py`)
- Schema-/Hint-Metadaten (`src/thermo0d/config/schema_meta.py`)
- Topology-Config-Editor (`src/thermo0d/gui/topology_config_editor.py`)
- Runner-Orchestrierung (`src/thermo0d/app/runner.py`)

Im Topology-Editor ist `postprocessing.plots.layouts.entries` als YAML-Mehrzeilenfeld editierbar.

## Konsolenstatus und Timing

Der Lauf gibt jetzt zusÃ¤tzlich Status- und Timingzeilen fÃ¼r die wichtigsten Schritte aus:

- `[run] wall_clock_s=... solver=...` misst den AusfÃ¼hrungsteil im `SimulationExecutor`
- `[analysis:cycle-index]`, `[analysis:cycle-summary]` messen die Analyse direkt nach dem Solver
- `[postprocessing:*]` zeigen Filterung, Sampling, Rekonstruktion, Integrale und Gesamtzeit
- `[csv]`, `[xlsx]`, `[csv:last-cycle-uniform]`, `[csv:check-report]`, `[html:check-report]` zeigen Status plus Laufzeit
- `[plot]`, `[plot.yaml]`, `[plot10.yaml]` zeigen Status plus Laufzeit der Plot-Erzeugung

Die frÃ¼here Gesamtliste aller Zyklen am Ende wird nicht mehr zusÃ¤tzlich ausgegeben. Bei SciPy-Solvern bleiben die Live-Zykluszeilen wÃ¤hrend der Integration erhalten.

## Ablageort fÃ¼r `plot.yaml`-Dateien

Layout-Dateien aus `postprocessing.plots.layouts.entries[].path` werden relativ zur verwendeten YAML-Konfigurationsdatei aufgelÃ¶st.

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


### VollstÃ¤ndiges Beispiel

Eine vollstÃ¤ndige Beispielkonfiguration auf Basis des A156A1-2V-REX-WH02-Vibe-Falls mit allen Postprocessing-Optionen liegt unter:

- `examples/A156A1-2V-REX-V09d_WH02-Vibe_postprocessing_full.yaml`

---

## Quelle: README_updated.md

Zeitstempel: `2026-04-21 15:36:20`

# thermo0d v0.4

## Konsolidierter Stand vom 01.04.2026

Dieses Archiv enthÃ¤lt den konsolidierten Gesamtstand eines datengetriebenen 0D-Kreisprozess-Frameworks mit klarer Trennung von Eingabe, Rechenkern, Ausgabe und GUI-Werkzeugen.

Der aktuelle Stand enthÃ¤lt zusÃ¤tzlich die zuletzt nachgezogenen Physik- und Auswerte-Hotfixes fÃ¼r:
- zentrale Auslagerung lokaler Energieterme aus `rhs.py`
- saubere Trennung von WandwÃ¤rme, Verbrennung und Evaporation in eigene Physik-Module
- korrigierte `angle_reference`-Logik fÃ¼r `absolute`, `compression_tdc` und `gas_exchange_tdc`
- Wrap-Logik fÃ¼r zyklusÃ¼bergreifende Fenster von Verbrennung und Evaporation
- konsistente Nutzung derselben Source-Term-Logik in Solver, Export und Plot-Auswertung

Enthalten sind auÃŸerdem die bereits zuvor nachgezogenen Konsolidierungs-Hotfixes:
- Topology-Editor: fehlende `schema_meta`-Imports behoben (`meta_for`, `SOLVER_KINDS`, `SAMPLING_MODES`, `ANGLE_REFERENCES`, `PROFILE_ANGLE_DOMAINS`)
- Topology-Editor: deaktivierte Teilmodelle werden beim Speichern bereinigt und rÃ¼ckwÃ¤rtskompatibel geladen
- Matrix-Builder: `combustion.model: none` und `evaporation.model: none` werden robust verarbeitet
- Topologie: `environment`-Volumina mit festen ZustÃ¤nden `pressure_Pa` / `temperature_K` und `orifice`-Verbindungen als Drosselpfad
- Loader/GUI: robuste mmâ†’m-Erkennung fÃ¼r `alpha_k_file`
- WandwÃ¤rme: einheitlicher Woschni-Pfad fÃ¼r Solver und Export

## Wesentliche Ã„nderungen dieses Stands

- `run_simulation.py` mit auswÃ¤hlbaren `simulated_args`-Presets, `project_A156A1` als Default
- Konfigurations-Versionierung mit echter Schema-Migration und RÃ¼ckwÃ¤rtskompatibilitÃ¤t
- formatierte Pydantic-, YAML- und Dateifehler in Loader und CLI
- projektweite Vordergrund-Dialoge Ã¼ber `src/thermo0d/gui/dialogs.py`
- robuster Alias-Editor mit Fehlerdialogen, exakten Dateipfaden und optionalem Start ohne Auto-Generierung
- PlotStyleEditor mit Y-Limits, Y-Min/Y-Max, Major/Minor-Step, Major/Minor-Grid, stabiler Inspector-Auswahl, echter Treffer-Markierung im Signalfilter und Subplot-DnD zwischen Figures
- ergonomische Plot-Editor-Erweiterungen: Achsenstil kopieren/einfÃ¼gen, auf Subplot oder alle Subplots anwenden, intelligente Auto-Limits aus Preview-Daten
- Startbedingungen bevorzugt Ã¼ber `initial_pressure_Pa` und `initial_temperature_K`, `initial_mass_kg` nur als Fallback
- Config-Kern weiter bereinigt: zusÃ¤tzliche BereichsprÃ¼fungen, schema-sichere Normalisierung und Master-Referenz-Config
- neues `scripts/config_tool.py` fÃ¼r `validate`, `upgrade`, `normalize`, `explain` und `diff`
- automatischer Last-Cycle-Checkreport als CSV, Konsolenreport und optional HTML
- fallklassenabhÃ¤ngige Ampelbewertung des Checkreports fÃ¼r geschlossene FÃ¤lle, Coldflow-Gaswechsel sowie gezÃ¼ndete 2T/4T-FÃ¤lle
- bereinigtes Archiv inkl. `doc/index.html`, `doc/app.js`, `doc/data.js` und `Projekte/data/`
- Hotfix fÃ¼r konsolidierte Pakete: `migrate_config_data(...)` und `migrate_yaml_text(...)` werden wieder exportiert

## Neu im Physikkern dieses Stands

### 1. Lokale Energieterme aus `rhs.py` ausgelagert

Die bisher in `src/thermo0d/physics/rhs.py` eingebetteten Modelle fÃ¼r Verbrennung und Evaporation wurden in eigene Module ausgelagert:

- `src/thermo0d/physics/heat_transfer.py`
- `src/thermo0d/physics/combustion.py`
- `src/thermo0d/physics/evaporation.py`
- `src/thermo0d/physics/source_terms.py`

Damit Ã¼bernimmt `rhs.py` wieder primÃ¤r die Bilanzgleichungen und die ZusammenfÃ¼hrung der einzelnen BeitrÃ¤ge.

### 2. Gemeinsame Source-Term-Auswertung

`src/thermo0d/physics/source_terms.py` bÃ¼ndelt die lokalen Energieterme je Zylindervolumen:

- `p*dV`
- WandwÃ¤rme
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

### 4. Wrap-Logik fÃ¼r zyklusÃ¼bergreifende Fenster

Verbrennungs- und Evaporationsfenster dÃ¼rfen jetzt Ã¼ber den Zyklusursprung laufen, zum Beispiel:
- `start_deg = 350`, `duration_deg = 30` in 2T
- `start_deg = 710`, `duration_deg = 40` in 4T

Die Aktivierung und Fortschrittsberechnung dieser Fenster wird jetzt korrekt zyklisch ausgewertet.

### 5. Plot-/GUI-Seite nachgezogen

Die Winkel- und Ereignislogik wurde fÃ¼r die Darstellungsseite mitgezogen:
- `src/thermo0d/output/plot_layout.py`
- `src/thermo0d/gui/plot_style_editor.py`

Damit bleiben Eventmarker, Layout-Auswertung und Solver-Referenzierung konsistent.

## Architektur

Die Codebasis trennt strikt zwischen:
- **Input**: Laden, Validieren, AuflÃ¶sen von Pfaden, Aufbau kompakter Simulationsdaten
- **Compute**: Solver, Integrationslauf, Kennwerte
- **Physics**: Kinematik, StrÃ¶mung, lokale Quell- und Senkterme
- **Output**: Sampling, Zeilenaufbau, CSV-/Excel-Export, Konsolenreporting
- **App/GUI**: Orchestrierung, Editoren, Werkzeuge

Der physikalische Rechenkern ist damit von YAML-Dateien, Exportformaten und GUI-Code getrennt.

## Paketstruktur

```text
src/thermo0d/
â”œâ”€ app/
â”œâ”€ compute/
â”œâ”€ config/
â”œâ”€ core/
â”œâ”€ gui/
â”œâ”€ input/
â”œâ”€ output/
â”œâ”€ physics/
â”œâ”€ config_versioning.py
â”œâ”€ main.py
â””â”€ version.py
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

### WandwÃ¤rme
Die WandwÃ¤rme wird zentral Ã¼ber `src/thermo0d/physics/heat_transfer.py` ausgewertet. Der aktuelle Pfad nutzt eine vereinfachte Woschni-artige HTC-Korrelation, die in Solver und Export konsistent verwendet wird.

### Verbrennung
`src/thermo0d/physics/combustion.py` implementiert aktuell eine vorgegebene Vibe-WÃ¤rmefreisetzung als Energieterm pro Zyklusfenster.

Wichtig:
- derzeit **keine** Speziesbilanz
- derzeit **keine** Oâ‚‚-Verbrauchsrechnung
- derzeit **keine** Kopplung an eine separate flÃ¼ssige Kraftstoffmasse

### Evaporation
`src/thermo0d/physics/evaporation.py` implementiert aktuell einen vorgegebenen Evaporations-Sinkterm als EnergiekÃ¼hlung im konfigurierten Fenster.

Wichtig:
- derzeit **keine** separate FlÃ¼ssigphase
- derzeit **keine** eigene Kraftstoff-Massenbilanz
- derzeit **keine** physikalische Verdampfungsrate aus Tropfen-/Filmzustand

### RHS
`src/thermo0d/physics/rhs.py` assembliert damit im Wesentlichen:
- Massenbilanz
- EnthalpiestrÃ¶me aus Verbindungen
- `p*dV`
- WandwÃ¤rme
- Verbrennung
- Evaporation

Die Datei enthÃ¤lt weiterhin die zentrale Differentialgleichung und Jacobian-UnterstÃ¼tzung, nicht mehr aber die komplette lokale Modelllogik im Detail.

## `run_simulation.py`

Das Skript unterstÃ¼tzt echte CLI-Argumente oder vordefinierte Presets Ã¼ber `simulated_args`.

Verhalten:
- mit CLI-Argumenten: normale AusfÃ¼hrung
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
- bei BestÃ¤tigung erfolgt eine **echte inhaltliche Migration**, nicht nur ein Versionsstempel
- `ConfigLoader` migriert Ã¤ltere Konfigurationen zusÃ¤tzlich auch beim normalen Laden im Speicher

Beispiele fÃ¼r automatisch migrierte Felder:
- `csv_sep` / `csv_delimiter` â†’ `csv_separator`
- `simulation.solver.method` â†’ `kind`
- `sampling.mode: angle` â†’ `crank_angle`
- `step_ca_deg` â†’ `step_deg`
- `alphak_file` â†’ `alpha_k_file`
- `forward_discharge_coefficient` / `reverse_discharge_coefficient` â†’ `forward_cd` / `reverse_cd`

## Startbedingungen

Neue Konfigurationen sollen bevorzugt diese Felder verwenden:

```yaml
initial_pressure_Pa: 101325.0
initial_temperature_K: 300.0
```

Ã„ltere Dateien mit `initial_mass_kg` bleiben lesbar und werden als Fallback unterstÃ¼tzt.

## Ausgabe / Sampling

`postprocessing.sampling` unterstÃ¼tzt:
- `time` mit `step_s`
- `crank_angle` mit `step_deg`

Optional kann zusÃ¤tzlich ein letzter Arbeitszyklus auf festem Winkelraster exportiert werden:

```yaml
postprocessing:
  final_cycle_uniform_angle_export:
    enabled: true
    step_deg: 1.0
```

Dabei gilt bewusst:
- 2T: `0â€¦359Â°`
- 4T: `0â€¦719Â°`

so dass kumulierte GrÃ¶ÃŸen am Dateiende nicht auf den Zyklusursprung zurÃ¼ckspringen.

## Ergebnis-Checkreport fÃ¼r den letzten Zyklus

Ãœber `postprocessing.check_report` kann zusÃ¤tzlich zum normalen CSV-Export ein automatischer PrÃ¼fbericht fÃ¼r den letzten Zyklus geschrieben werden.

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

Der Checkreport enthÃ¤lt unter anderem:
- Punktzahl und Winkelbereich des letzten Zyklus
- `pmin`, `pmax`, `Tmin`, `Tmax`, `mmin`, `mmax`
- integrierte ZyklusgrÃ¶ÃŸen fÃ¼r Masse, Enthalpie, WandwÃ¤rme, zugefÃ¼hrte Energie, Verdampfungsenthalpie und Kolbenarbeit
- Massen- und EnergiebilanzrestgrÃ¶ÃŸen absolut und relativ
- `overall_status` als Gesamtampel
- Zylindergeometrie in mm / mmÂ² / cmÂ³: `bore_mm`, `stroke_mm`, `conrod_mm`, `bore_area_mm2`, `swept_cm3`, `clearance_cm3`
- Ventilgeometrie in mm / mmÂ²: `lift_max_mm`, `A_ref_mm2`, `A_eff_forward_max_mm2`, `A_eff_reverse_max_mm2`
- bei Slot-FÃ¤llen zusÃ¤tzlich die maximalen SlotflÃ¤chen, inkl. `A_eff_forward_max_mm2` und `A_eff_reverse_max_mm2`

Die Ampel wird nicht mehr mit einem einzigen starren Satz Grenzwerte bewertet, sondern abhÃ¤ngig von einer automatisch erkannten Fallklasse:
- `closed_or_settling`
- `coldflow_gas_exchange`
- `fired_gas_exchange_4T`
- `fired_scavenged_2T`

Damit werden geschlossene SetzfÃ¤lle strenger bewertet als durchgesetzte MotorfÃ¤lle, und gezÃ¼ndete 2T/4T-FÃ¤lle erhalten passendere Druck-, Temperatur- und Bilanzgrenzen.

ZusÃ¤tzlich gilt jetzt fÃ¼r die Lauf-Ausgabe:
- Exportartefakte (`csv`, `xlsx`, Plotdateien, Checkreport-Dateien) werden in der Konsole nur noch mit `OK`, `WARN` oder `FAILED` gemeldet.
- VollstÃ¤ndige Pfade und Verzeichnisse werden dafÃ¼r nicht mehr in die Konsole geschrieben.

## Tabellen-Loader / `alpha_k_file`

Der Loader fÃ¼r `alpha_k_file` erkennt jetzt robust, ob die Lift-Achse in mm statt m vorliegt. Die Autokonvertierung nach m greift, wenn mindestens eines davon zutrifft:
- Header-Hinweis wie `lift_mm`, `hub_mm` oder vergleichbar
- offensichtlicher Wertebereich der Liftspalte (z. B. 1 â€¦ 10 statt 0.001 â€¦ 0.010)

Dieselbe mmâ†’m-Logik wird jetzt sowohl im Simulations-Loader als auch in der GUI-/Editor-Vorschau verwendet.

## Massenstrom-Vorzeichenkonvention

Die interne StrÃ¶mungsrichtung wird topologisch pro Verbindung Ã¼ber `from_idx -> to_idx` definiert.

Daraus folgt:
- `<connection>_mdot_kg_per_s` ist **positiv** fÃ¼r StrÃ¶mung in definierter Verbindungsrichtung
- derselbe Wert ist **negativ** bei realer Gegenrichtung
- bilanziert wird mit `-mdot` auf der linken und `+mdot` auf der rechten Seite

ZusÃ¤tzlich werden exportseitig lesbare Betragssignale gebildet:
- `<cyl>_mdot_in_kg_per_s` immer positiv
- `<cyl>_mdot_out_kg_per_s` immer positiv

## Config-Workflow

### Config-Kern / Validierung
- zusÃ¤tzliche Bereichs- und KonsistenzprÃ¼fungen fÃ¼r Solver, Kinematik, Verbrennung, Verdampfung, Slots und Winkelraster
- schema-sichere Normalisierung Ã¼ber `normalize_config_data(...)`
- RÃ¼ckwÃ¤rtskompatibilitÃ¤t bleibt erhalten; Migrationen laufen weiterhin Ã¼ber `migrate_config_data(...)`

### Referenzdateien
- `examples/config_master_reference.yaml` ist die vollstÃ¤ndige aktuelle Ausgangsvorlage
- `examples/config_schema_documented.yaml` bleibt die ausfÃ¼hrlich kommentierte Dokumentationsvorlage

### Config-Tool

```bash
python scripts/config_tool.py validate  Projekte/config.yaml
python scripts/config_tool.py upgrade   Projekte/config.yaml --output Projekte/config_upgraded.yaml
python scripts/config_tool.py normalize Projekte/config.yaml --output Projekte/config_normalized.yaml
python scripts/config_tool.py explain   Projekte/config.yaml
python scripts/config_tool.py diff      Projekte/config.yaml Projekte/config_normalized.yaml
```

Kommandos:
- `validate`: gegen aktuelles Schema prÃ¼fen
- `upgrade`: alte Feldnamen / Altstrukturen migrieren
- `normalize`: kanonische Form schreiben
- `explain`: Kurzfassung oder Pfadinhalt ausgeben
- `diff`: zwei Dateien oder eine Datei gegen die kanonische Form vergleichen

## GUI-Werkzeuge

### EngineGasExchangeEditor
- Bearbeitung von `engine` und `gasexchange`
- Timing-Preview mit rechter Y-Achse fÃ¼r Kolbenweg ab UT oder Zylindervolumen
- Vordergrund-Dialoge und robuste Dateidialoge
- RÃ¼ckwÃ¤rtskompatible Konfigurationsmigration

### PlotStyleEditor
- Y-Limits, Y-Min/Y-Max, Major/Minor-Step, Major/Minor-Grid
- X-Presets: `0â€¦360`, `0â€¦720`, `-180â€¦180`, `-360â€¦360`, Auto
- Signalfilter mit Aufklappen, echter Treffer-Markierung, TrefferzÃ¤hler, erster Treffer direkt sichtbar
- stabiler Inspector ohne RÃ¼cksprung auf das erste Element
- Subplots per Drag & Drop zwischen Figures verschiebbar, mit `Strg` kopierbar, inkl. Live-Feedback
- Achsenstil kopieren/einfÃ¼gen
- Achsenstil auf aktuellen Subplot oder alle Subplots anwenden
- intelligente Auto-Limits aus den tatsÃ¤chlich verfÃ¼gbaren Preview-Daten
- nachgezogene Winkel-/Eventlogik passend zu `absolute` und zyklischem Wrap

### TopologyConfigEditor
- Eigenschaften-Panel mit schema-basierten Hinweisen
- Pflichtfelder werden mit `*` markiert
- Tooltips zeigen Typ, Pflichtstatus, Default und erlaubte Werte
- kompakte Kontext-Hinweise pro Root / Cylinder / Plenum / Valve / Slot

## Tests

FÃ¼r die zuletzt nachgezogenen PhysikÃ¤nderungen wurden insbesondere die folgenden Testpfade erweitert bzw. ergÃ¤nzt:
- `tests/test_rhs_helpers_extended.py`
- `tests/test_flow_kinematics_extended.py`
- `tests/test_parser_rhs.py`

Diese Tests decken insbesondere ab:
- Referenzierung mit lokalem vs. globalem Winkel
- Wrap-Fenster Ã¼ber den Zyklusursprung
- Parser-/RHS-KompatibilitÃ¤t nach der Source-Term-Auslagerung


## Postprocessing: Plot-Ausgabe, Layout-Dateien und Konsolen-Schalter

Der Root-Block `postprocessing` unterstÃ¼tzt jetzt zusÃ¤tzlich konfigurierbare Plot- und Konsolenausgabe:

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
- `postprocessing.plots.source` wÃ¤hlt die Datenbasis fÃ¼r Standardplots und Layout-Rendering:
  - `last_cycle_uniform`: letzter Zyklus auf festem Winkelraster
  - `export_rows`: normale Exporttabelle
- `postprocessing.plots.output_dir` setzt optional einen Zielordner fÃ¼r mit `plot.yaml`-Layouts erzeugte Grafiken.
- `postprocessing.plots.pressure_plot.*` steuert den einfachen Standard-Druckplot separat.
- `postprocessing.plots.layouts.auto_create_defaults` erzeugt bei Bedarf `plot.yaml` und `plot10.yaml`, falls keine EintrÃ¤ge angegeben sind.
- `postprocessing.plots.layouts.entries` ist eine Liste externer Plot-Layout-Dateien mit optionalem PrÃ¤fix.
- `postprocessing.console.*` schaltet die Konsolenabschnitte fÃ¼r Run-Summary, Cycle-Summary, Checkreport und Geometrie getrennt.

### Editoren und Migration

Die neuen Felder sind integriert in:
- Pydantic-Config-Modelle (`src/thermo0d/config/models.py`)
- Config-Migration (`src/thermo0d/config_versioning.py`)
- Schema-/Hint-Metadaten (`src/thermo0d/config/schema_meta.py`)
- Topology-Config-Editor (`src/thermo0d/gui/topology_config_editor.py`)
- Runner-Orchestrierung (`src/thermo0d/app/runner.py`)

Im Topology-Editor ist `postprocessing.plots.layouts.entries` als YAML-Mehrzeilenfeld editierbar.

## Konsolenstatus und Timing

Der Lauf gibt jetzt zusÃ¤tzlich Status- und Timingzeilen fÃ¼r die wichtigsten Schritte aus:

- `[run] wall_clock_s=... solver=...` misst den AusfÃ¼hrungsteil im `SimulationExecutor`
- `[analysis:cycle-index]`, `[analysis:cycle-summary]` messen die Analyse direkt nach dem Solver
- `[postprocessing:*]` zeigen Filterung, Sampling, Rekonstruktion, Integrale und Gesamtzeit
- `[csv]`, `[xlsx]`, `[csv:last-cycle-uniform]`, `[csv:check-report]`, `[html:check-report]` zeigen Status plus Laufzeit
- `[plot]`, `[plot.yaml]`, `[plot10.yaml]` zeigen Status plus Laufzeit der Plot-Erzeugung

Die frÃ¼here Gesamtliste aller Zyklen am Ende wird nicht mehr zusÃ¤tzlich ausgegeben. Bei SciPy-Solvern bleiben die Live-Zykluszeilen wÃ¤hrend der Integration erhalten.

## Ablageort fÃ¼r `plot.yaml`-Dateien

Layout-Dateien aus `postprocessing.plots.layouts.entries[].path` werden relativ zur verwendeten YAML-Konfigurationsdatei aufgelÃ¶st.

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


### VollstÃ¤ndiges Beispiel

Eine vollstÃ¤ndige Beispielkonfiguration auf Basis des A156A1-2V-REX-WH02-Vibe-Falls mit allen Postprocessing-Optionen liegt unter:

- `examples/A156A1-2V-REX-V09d_WH02-Vibe_postprocessing_full.yaml`


## Free-Piston

Current status: **A.1 green** and **A.2 green** for the minimal free-piston path.
The free-piston builder no longer requires a classical cylinder placeholder in `preprocessing.volumes`; an internal single-cylinder topology is synthesized when the list is empty. The A.2 path integrates `m`, `U`, `x`, and `v` with a dedicated free-piston RHS and time-based output.

---

## Quelle: STROKE_FRAME_EXPORT_QUICKSTART.md

Zeitstempel: `2026-04-22 07:51:05`

# ðŸš€ Stroke Frame Export â€“ Quick Start Guide

## What's New

Neue Funktionen fÃ¼r optimiertes Plotting von UT-OT-UT HÃ¼ben mit Frame-Export und Video-Generierung.

### Implementierte Features

âœ… **Frame-Generierung** (`export_free_piston_last_ut_ot_ut_frames()`)
- Konfigurierbare Kurbelwinkel-Schrittweite (1Â°â€“10Â° empfohlen)
- Automatische UT/OT-Detektion
- Hochwertige Annotationen (Farben, Marker, Pfeile)
- Optional: MP4-Video-Export

âœ… **Plot-Konfiguration** (YAML)
- Neue Datei: `Projekte/plot_stroke_optimization.yaml`
- 4 vordefinierte Figures (pV, Druck vs. Winkel, Multi-Param, Flow)
- UT/OT-Events vorkonfiguriert
- Farbblind-freundliche Paletten

âœ… **Test-Suite** (`tests/test_stroke_frame_export.py`)
- Unit-Tests fÃ¼r Frame-Generierung
- Synthetic Stroke-Data fÃ¼r Tests
- Performance-Benchmark

âœ… **Integrations-Template** (`src/thermo0d/output/stroke_export_integration.py`)
- Zeigt wie man in Runner integriert
- Config-Template
- Logging & Error-Handling

âœ… **Dokumentation**
- Umfassender Guide: `src/STROKE_PLOT_OPTIMIZATION_GUIDE.md`
- Beispiel-Script: `examples_stroke_export.py`
- Config-Vorlagen

---

## ðŸŽ¯ Quick Start

### 1. Einfacher Test (ohne Simulation)

```bash
python examples_stroke_export.py --mode fast
```

**Oder mit Config**:
```bash
python examples_stroke_export.py \
  --config Projekte/config.yaml \
  --mode standard \
  --output results/my_strokes
```

**Optimize-Level**:
- `fast`: 10Â° step, ~36 Frames, ~10s
- `standard`: 5Â° step, ~72 Frames, ~60s
- `detailed`: 2Â° step, ~180 Frames, ~2min
- `ultra`: 1Â° step, ~360 Frames, ~5min
- `batch`: Alle oben, kombiniert

### 2. Tests ausfÃ¼hren

```bash
python -m pytest tests/test_stroke_frame_export.py -v
```

**Oder direkt**:
```bash
python tests/test_stroke_frame_export.py
```

### 3. In bestehenden Runner integrieren

**In `src/thermo0d/app/runner.py`** nach der pV-Plot-Generierung hinzufÃ¼gen:

```python
# Nach existing plots...

from thermo0d.output.stroke_export_integration import export_stroke_frames

if bundle.free_piston_last_ut_ot_ut_export_enabled:
    stroke_paths = export_stroke_frames(
        bundle=bundle,
        export_rows=export_rows,
        config=config,
        project_root=project_root,
        run_config_path=config_path,
    )
    if stroke_paths:
        print(f"âœ“ Stroke frames: {stroke_paths[0].parent}")
```

### 4. Config aktivieren

**In `Projekte/config.yaml`**:

```yaml
postprocessing:
  free_piston_last_ut_ot_ut_export:
    enabled: true        # â† Aktivieren
    step_deg: 5.0        # 72 Frames
    axis_min_deg: 0.0
    axis_max_deg: 360.0
```

### 5. Plot-Config verwenden

```bash
# Nutze optimierte Plot-Config:
python scripts/run_plot_editor.py Projekte/plot_stroke_optimization.yaml
```

---

## ðŸ“ Dateien-Ãœbersicht

| Datei | Beschreibung |
|-------|-------------|
| `src/thermo0d/output/plots.py` | **Neu**: `export_free_piston_last_ut_ot_ut_frames()` |
| `src/thermo0d/output/plot_layout.py` | **Neu**: `render_plot_project_with_frame_export()` |
| `src/STROKE_PLOT_OPTIMIZATION_GUIDE.md` | Umfassender Guide (10 Kapitel) |
| `Projekte/plot_stroke_optimization.yaml` | Vorlage mit 4 Figures |
| `src/thermo0d/output/stroke_export_integration.py` | Integrations-Template fÃ¼r Runner |
| `tests/test_stroke_frame_export.py` | Test-Suite mit Benchmarks |
| `examples_stroke_export.py` | Standalone Example-Script |

---

## ðŸ”§ API-Referenz

### `export_free_piston_last_ut_ot_ut_frames()`

```python
from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames

paths = export_free_piston_last_ut_ot_ut_frames(
    bundle=bundle,                 # ModelBundle
    rows=export_rows,              # CSV data (list[dict])
    output_dir="results/frames",   # Output path
    step_deg=5.0,                  # Kurbelwinkel-Schritt
    axis_min_deg=0.0,              # Min angle
    axis_max_deg=360.0,            # Max angle
    export_video=True,             # MP4 export?
    video_fps=30,                  # Video framerate
    run_config_path="config.yaml"  # Config path
) â†’ list[str]  # Pfade zu Frames + Video
```

**Output**:
```
results/frames/
â”œâ”€â”€ frame_0000_angle_000deg.png
â”œâ”€â”€ frame_0001_angle_005deg.png
â”œâ”€â”€ frame_0002_angle_010deg.png
â”œâ”€â”€ ...
â””â”€â”€ last_cycle_animation.mp4
```

---

## ðŸ“Š Beispiel: Batch-Generierung

```python
from pathlib import Path
from thermo0d.app.runner import simulate
from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames

# 1. Simulation
config = Path("Projekte/config.yaml")
bundle, export_rows = simulate(str(config))

# 2. Multiple Export-Level
for step_deg in [1.0, 5.0, 10.0]:
    output = Path("results") / f"stroke_step_{int(step_deg)}deg"
    export_free_piston_last_ut_ot_ut_frames(
        bundle, export_rows, output,
        step_deg=step_deg,
        export_video=True
    )
    print(f"âœ“ {output}")
```

---

## ðŸŽ¨ Design-Highlights

- **Farbblind-freundlich**: `#1f77b4` (Blau), `#ff7f0e` (Orange), `#2ca02c` (GrÃ¼n)
- **Kontrastreiche Overlays**: Schwarze RÃ¤nder, weiÃŸe HintergrÃ¼nde
- **AussagekrÃ¤ftige Annotationen**: UT/OT-Marker, Winkelbeschriftung, Daten-Footer
- **Responsive Schriften**: Skaliert nach DPI & Figure-GrÃ¶ÃŸe

---

## âš¡ Performance-Tipps

| Ziel | Einstellung | Zeit |
|-----|-----------|------|
| **Preview** | `step_deg=10.0`, `export_video=False` | ~5s |
| **Standard** | `step_deg=5.0`, `export_video=True` | ~60s |
| **Detailed** | `step_deg=2.0`, `export_video=True` | ~2min |
| **Ultra** | `step_deg=1.0`, `export_video=True` | ~5min |

**Memory-Optimierungen**:
- Nutze `frame_step=10` fÃ¼r groÃŸe Datenmengen
- Lazy-Loading: Nur benÃ¶tigte Frames rendern
- Video-Codec `libx264` statt `prores`

---

## ðŸ› Bekannte Probleme & LÃ¶sungen

| Problem | LÃ¶sung |
|---------|--------|
| **ImportError: imageio** | `pip install imageio imageio-ffmpeg` |
| **UT/OT nicht erkannt** | Daten-ValiditÃ¤t prÃ¼fen (velocity sign-changes) |
| **Frames zu groÃŸ** | DPI senken oder PNG â†’ JPEG |
| **Speicher voll** | `frame_step` erhÃ¶hen oder Daten in Batches laden |
| **Langsam** | `step_deg` erhÃ¶hen (z.B. 10.0 statt 1.0) |

---

## ðŸ“ NÃ¤chste Schritte

1. **Tests ausfÃ¼hren**:
   ```bash
   python tests/test_stroke_frame_export.py
   ```

2. **Example testen**:
   ```bash
   python examples_stroke_export.py --mode fast
   ```

3. **Runner integrieren**:
   - Kopiere Integration-Code aus `stroke_export_integration.py`
   - Aktiviere in Config

4. **Eigene Plots anpassen**:
   - Editiere `plot_stroke_optimization.yaml`
   - Passe Farben/Achsen nach Bedarf an

---

## ðŸ“š Weitere Ressourcen

- **Umfassender Guide**: `src/STROKE_PLOT_OPTIMIZATION_GUIDE.md`
- **Test-Beispiele**: `tests/test_stroke_frame_export.py`
- **Integration-Vorlage**: `src/thermo0d/output/stroke_export_integration.py`
- **Example-Script**: `examples_stroke_export.py` (mit 4 Optimize-Level)
- **Plot-Config**: `Projekte/plot_stroke_optimization.yaml`

---

**Autor**: Optimization for MotorSim V03  
**Datum**: 2026-04-22  
**Status**: âœ… Ready for Production

---

## Quelle: README_project.md

Zeitstempel: `2026-05-12 07:41:13`

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

---
