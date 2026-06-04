# Schlankes Postprocessing

Die neue Pipeline ist optional. Der bisherige Export bleibt aktiv, solange in der Simulationskonfiguration nichts umgestellt wird.

## Aktivierung

In der normalen Simulationskonfiguration:

```yaml
postprocessing:
  mode: pipeline
  config: postprocessing.yaml
```

`postprocessing.config` zeigt auf eine separate Pipeline-Datei. Relative Pfade werden relativ zur Simulationskonfiguration interpretiert.

## Pipeline-Konfiguration

Beispiel:

```yaml
version: 1

raw:
  enabled: true
  path: raw/run_raw.npz
  compression: compressed
  dtype: float32

signals:
  selected:
    - t_s
    - cycle_index
    - cylinder_1_m_kg
    - cylinder_1_wall_heat_cycle_J
  include_kinds: [raw, integral]
  remove_zero_columns: true
  zero_tolerance: 0.0
  keep_zero_selected: false

csv:
  enabled: true
  path: csv/signals.csv
  separator: ";"
  include_units_row: true
  include_kind_row: true

summary:
  enabled: true
  path: summary/run_summary.yaml
  text_path: summary/run_summary.txt

offline:
  enabled: true
  allow_reconstruction: false
  allow_derivatives: false
```

## Signalarten

- `raw`: Zustände direkt aus dem Solver-Zustandsvektor und `t_s`/`cycle_index`.
- `derivative`: Zustandsableitungen `d_<state>_dt`, nur wenn explizit ausgewählt. Das kostet nur im Postprocessing Zeit, nicht im Solver.
- `reconstructed`: rekonstruierte Signale aus vorhandenen Modell- und Geometriedaten.
- `integral`: Zeitintegrale aus vorhandenen Leistungs- oder Massenstromsignalen, zum Beispiel `*_wall_heat_cycle_J`.

## Raw-Archiv

Das Raw-Archiv ist eine kompakte `.npz`-Datei mit:

- `t_s`
- `y`
- `cycle_index`
- `state_names`
- `state_units`
- `architecture`
- `config_path`
- `config_hash`

Damit bleiben die Rohdaten performant und kompakt erhalten.

## Offline-Reprocessing

Aus einem vorhandenen Raw-Archiv kann CSV und Summary neu erzeugt werden:

```powershell
python scripts/run_postprocessing_pipeline.py `
  --raw Projekte/variants/results/run/raw/run_raw.npz `
  --config Projekte/variants/postprocessing.yaml `
  --outdir Projekte/variants/results/run/reprocessed
```

Offline sind standardmäßig nur Raw-Signale, Nullspaltenfilter, Integrale aus vorhandenen Spalten und Summary aktiv. Rekonstruktionen und RHS-Ableitungen bleiben offline deaktiviert, weil sie vollständigen Modellkontext benötigen.

## Alias Editor

Der Alias Editor kann aus den markierten Export-Signalen direkt eine `postprocessing.yaml` schreiben. Dafür die gewünschten Signale markieren und `Pipeline-Config schreiben` verwenden.
