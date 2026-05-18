# 🚀 Stroke Frame Export – Quick Start Guide

## What's New

Neue Funktionen für optimiertes Plotting von UT-OT-UT Hüben mit Frame-Export und Video-Generierung.

### Implementierte Features

✅ **Frame-Generierung** (`export_free_piston_last_ut_ot_ut_frames()`)
- Konfigurierbare Kurbelwinkel-Schrittweite (1°–10° empfohlen)
- Automatische UT/OT-Detektion
- Hochwertige Annotationen (Farben, Marker, Pfeile)
- Optional: MP4-Video-Export

✅ **Plot-Konfiguration** (YAML)
- Neue Datei: `Projekte/plot_stroke_optimization.yaml`
- 4 vordefinierte Figures (pV, Druck vs. Winkel, Multi-Param, Flow)
- UT/OT-Events vorkonfiguriert
- Farbblind-freundliche Paletten

✅ **Test-Suite** (`tests/test_stroke_frame_export.py`)
- Unit-Tests für Frame-Generierung
- Synthetic Stroke-Data für Tests
- Performance-Benchmark

✅ **Integrations-Template** (`src/thermo0d/output/stroke_export_integration.py`)
- Zeigt wie man in Runner integriert
- Config-Template
- Logging & Error-Handling

✅ **Dokumentation**
- Umfassender Guide: `src/STROKE_PLOT_OPTIMIZATION_GUIDE.md`
- Beispiel-Script: `examples_stroke_export.py`
- Config-Vorlagen

---

## 🎯 Quick Start

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
- `fast`: 10° step, ~36 Frames, ~10s
- `standard`: 5° step, ~72 Frames, ~60s
- `detailed`: 2° step, ~180 Frames, ~2min
- `ultra`: 1° step, ~360 Frames, ~5min
- `batch`: Alle oben, kombiniert

### 2. Tests ausführen

```bash
python -m pytest tests/test_stroke_frame_export.py -v
```

**Oder direkt**:
```bash
python tests/test_stroke_frame_export.py
```

### 3. In bestehenden Runner integrieren

**In `src/thermo0d/app/runner.py`** nach der pV-Plot-Generierung hinzufügen:

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
        print(f"✓ Stroke frames: {stroke_paths[0].parent}")
```

### 4. Config aktivieren

**In `Projekte/config.yaml`**:

```yaml
postprocessing:
  free_piston_last_ut_ot_ut_export:
    enabled: true        # ← Aktivieren
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

## 📁 Dateien-Übersicht

| Datei | Beschreibung |
|-------|-------------|
| `src/thermo0d/output/plots.py` | **Neu**: `export_free_piston_last_ut_ot_ut_frames()` |
| `src/thermo0d/output/plot_layout.py` | **Neu**: `render_plot_project_with_frame_export()` |
| `src/STROKE_PLOT_OPTIMIZATION_GUIDE.md` | Umfassender Guide (10 Kapitel) |
| `Projekte/plot_stroke_optimization.yaml` | Vorlage mit 4 Figures |
| `src/thermo0d/output/stroke_export_integration.py` | Integrations-Template für Runner |
| `tests/test_stroke_frame_export.py` | Test-Suite mit Benchmarks |
| `examples_stroke_export.py` | Standalone Example-Script |

---

## 🔧 API-Referenz

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
) → list[str]  # Pfade zu Frames + Video
```

**Output**:
```
results/frames/
├── frame_0000_angle_000deg.png
├── frame_0001_angle_005deg.png
├── frame_0002_angle_010deg.png
├── ...
└── last_cycle_animation.mp4
```

---

## 📊 Beispiel: Batch-Generierung

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
    print(f"✓ {output}")
```

---

## 🎨 Design-Highlights

- **Farbblind-freundlich**: `#1f77b4` (Blau), `#ff7f0e` (Orange), `#2ca02c` (Grün)
- **Kontrastreiche Overlays**: Schwarze Ränder, weiße Hintergründe
- **Aussagekräftige Annotationen**: UT/OT-Marker, Winkelbeschriftung, Daten-Footer
- **Responsive Schriften**: Skaliert nach DPI & Figure-Größe

---

## ⚡ Performance-Tipps

| Ziel | Einstellung | Zeit |
|-----|-----------|------|
| **Preview** | `step_deg=10.0`, `export_video=False` | ~5s |
| **Standard** | `step_deg=5.0`, `export_video=True` | ~60s |
| **Detailed** | `step_deg=2.0`, `export_video=True` | ~2min |
| **Ultra** | `step_deg=1.0`, `export_video=True` | ~5min |

**Memory-Optimierungen**:
- Nutze `frame_step=10` für große Datenmengen
- Lazy-Loading: Nur benötigte Frames rendern
- Video-Codec `libx264` statt `prores`

---

## 🐛 Bekannte Probleme & Lösungen

| Problem | Lösung |
|---------|--------|
| **ImportError: imageio** | `pip install imageio imageio-ffmpeg` |
| **UT/OT nicht erkannt** | Daten-Validität prüfen (velocity sign-changes) |
| **Frames zu groß** | DPI senken oder PNG → JPEG |
| **Speicher voll** | `frame_step` erhöhen oder Daten in Batches laden |
| **Langsam** | `step_deg` erhöhen (z.B. 10.0 statt 1.0) |

---

## 📝 Nächste Schritte

1. **Tests ausführen**:
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

## 📚 Weitere Ressourcen

- **Umfassender Guide**: `src/STROKE_PLOT_OPTIMIZATION_GUIDE.md`
- **Test-Beispiele**: `tests/test_stroke_frame_export.py`
- **Integration-Vorlage**: `src/thermo0d/output/stroke_export_integration.py`
- **Example-Script**: `examples_stroke_export.py` (mit 4 Optimize-Level)
- **Plot-Config**: `Projekte/plot_stroke_optimization.yaml`

---

**Autor**: Optimization for MotorSim V03  
**Datum**: 2026-04-22  
**Status**: ✅ Ready for Production
