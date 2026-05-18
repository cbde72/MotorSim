# Thermo0D / MotorSim – bereinigter Projektstand

Dieser Stand enthält den aktuellen Python-Code, die relevanten Projektdateien, dokumentierte Varianten und Plot-Layouts in einer bereinigten Struktur.

Ziele dieses bereinigten Stands:
- keine temporären Dateien, keine Cache-Dateien, keine Backup-Kopien
- keine separaten Free-Piston-Animations-HTMLs
- kein `engine_gasexchange_editor2.py`
- keine `examples/`-Struktur mehr; dokumentierte Beispiel- und Variantenkonfigurationen liegen unter `Projekte/variants/`
- nur eine zentrale `README.md`

## Struktur

- `src/thermo0d/` – Quellcode
- `scripts/` – Startskripte und Hilfsskripte
- `tests/` – automatisierte Tests
- `Projekte/` – Projektdateien, Referenzkonfigurationen und Plot-Layouts
- `Projekte/variants/` – dokumentierte Varianten und Beispielkonfigurationen
- `doc/` – Projektdokumentation

## Wichtige Varianten unter `Projekte/variants/`

### Klassische Referenzfälle
- `config_1cyl_2t.yaml`
- `config_1cyl_4t.yaml`
- `config_master_reference.yaml`
- `config_schema_documented.yaml`
- `config_woschni_variants_documented.yaml`

### Free-Piston-Fälle
- `free_piston_phase_a.yaml`
- `free_piston_phase_a2.yaml`
- `free_piston_phase_a3.yaml`
- `free_piston_phase_c.yaml`
- `free_piston_coldflow.yaml`
- `free_piston_700g_ringdown_25hz.yaml`

### Plot-Dateien
- `plot.yaml`
- `plot10.yaml`
- `plot_fp.yaml`

## Start

### Simulation ausführen
```bash
python scripts/run_simulation.py --config Projekte/variants/config_1cyl_4t.yaml
```

### Free-Piston-Fall ausführen
```bash
python scripts/run_simulation.py --config Projekte/variants/free_piston_coldflow.yaml
```

### Plot-Editor
```bash
python scripts/run_plot_editor.py
```

### Gaswechsel-Editor
```bash
python scripts/run_gasexchange_editor.py
```

### Topologie-Editor
```bash
python scripts/run_topology_config_editor.py
```

## Free-Piston-Konzept im aktuellen Stand

Der Free-Piston-Pfad ist als eigener Modellzweig umgesetzt. Die gemeinsame Topologie bleibt erhalten; die Bewegung entsteht aus translatorischen Zuständen statt aus Kurbelkinematik.

Wesentliche Größen:
- `x_min_m`, `x_max_m` definieren BDC und TDC
- Hub = `x_max_m - x_min_m`
- Abstand von TDC = `x_max_m - x`
- Slots mit `opening_mode: by_distance` werden relativ zu diesem TDC-Abstand geöffnet

Typische Free-Piston-Konfiguration:
- `modeling.architecture: free_piston`
- `free_piston.initial_conditions.*`
- `free_piston.mechanics.*`
- `free_piston.friction.*`
- `free_piston.load.*`
- `free_piston.bounce.*`
- Topologie weiter unter `preprocessing.volumes` und `preprocessing.connections`

## Plot-Konzept

Die Plot-Layouts liegen projektweit unter:
- `Projekte/plot*.yaml`
- `Projekte/plot_configs/`
- `Projekte/variants/plot*.yaml`

Der dokumentierte Free-Piston-Plot-Satz ist:
- `Projekte/variants/plot_fp.yaml`

Er deckt typischerweise ab:
- Drücke
- Kolbenweg
- TDC-Abstand
- Geschwindigkeit und Beschleunigung
- Slot-Höhen
- effektive Öffnungsquerschnitte
- Massenströme
- Kräfte
- Volumina
- thermische Größen und Bilanzgrößen

## Dokumentierte Beispielnutzung

### 1) Free-Piston Phase A
```bash
python scripts/run_simulation.py --config Projekte/variants/free_piston_phase_a.yaml
```

### 2) Free-Piston Phase C
```bash
python scripts/run_simulation.py --config Projekte/variants/free_piston_phase_c.yaml
```

### 3) Free-Piston Coldflow mit Plotlayout
```bash
python scripts/run_simulation.py --config Projekte/variants/free_piston_coldflow.yaml
```
Verwende dazu als Layout:
- `Projekte/variants/plot_fp.yaml`

## Bereinigung gegenüber früheren Zwischenständen

Entfernt wurden insbesondere:
- `examples/`
- temporäre Ergebnisordner
- Cache-Dateien und kompilierte Artefakte
- Backup-/Kopie-Dateien
- zusätzliche README-Dubletten
- separate Free-Piston-Animations-HTMLs
- `engine_gasexchange_editor2.py`

## Hinweise

- Einige ältere Projektdateien unter `Projekte/` bleiben bewusst erhalten, weil sie reale Referenzstände und Vergleichsfälle darstellen.
- Die dokumentierten und bevorzugten Startpunkte liegen jetzt unter `Projekte/variants/`.
- Falls einzelne lokale Workflows bisher hart auf `examples/` verwiesen haben, müssen sie auf `Projekte/variants/` umgestellt werden.
