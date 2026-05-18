# Thermo0D Doc Editor (installationsfrei)

Dieser `doc/`-Ordner enthält eine statische Browser-Oberfläche für die aktuelle `config.yaml`.

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

Dann öffnet sich der Editor unter `http://127.0.0.1:8765/doc/index.html`.

## Wichtiger Hinweis zum 404-Fehler

`index.html` referenziert jetzt die mitgelieferten Dateien `data.js` und `app.js` im selben Ordner.
Der frühere 404 auf `127.0.0.1` trat auf, wenn diese JavaScript-Dateien im Archiv fehlten.
Im aktuellen Stand sind beide Dateien enthalten.

## UI-Stack

Der statische Editor nutzt CDN-basiert:

- Tailwind CSS
- KaTeX für Formelkarten
- SweetAlert2 für Aktionen und Feedback
- Phosphor Icons
- Plotly für technische Diagramme

Es ist keine lokale Paketinstallation notwendig.
Für CDN-Ressourcen ist beim Öffnen eine Internetverbindung sinnvoll.

## Konfigurationsversionierung

Die Beispieloberfläche dokumentiert jetzt Schema v4.
In den Desktop-Editoren werden beim Laden alter Konfigurationen nach Bestätigung automatische Migrationen ausgeführt, unter anderem:

- `postprocessing.csv_sep` beziehungsweise `csv_delimiter` → `csv_separator`
- `simulation.solver.method` → `kind`
- `preprocessing.features.heat_transfer` → `wall_heat`
- `sampling.mode: angle` → `crank_angle`
- `step_ca_deg` → `step_deg`
- `angle_ref`, `opening_ref`, `alphak_file`, `number_of_holes` → aktuelle Feldnamen
- Ergänzung von `postprocessing.final_cycle_uniform_angle_export`
