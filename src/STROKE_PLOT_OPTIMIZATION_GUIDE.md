# Optimierungsguide: Plotting von UT-OT-UT Hüben

## Übersicht

Dieses Dokument beschreibt Optimierungen für die Visualisierung und das Exportieren von Bildern des letzten vollständigen Hubes (UT → OT → UT) mit fortgeschrittener Konfiguration und Design.

---

## 1. Neue Funktionen

### 1.1 Frame-Export-Funktion: `export_free_piston_last_ut_ot_ut_frames()`

**Ort**: `src/thermo0d/output/plots.py`

```python
def export_free_piston_last_ut_ot_ut_frames(
    bundle,
    rows: list[dict[str, float | int]],
    output_dir: str | Path,
    step_deg: float = 1.0,           # Kurbelwinkel-Schrittweite
    axis_min_deg: float = 0.0,       # Min. Achse
    axis_max_deg: float = 360.0,     # Max. Achse
    export_video: bool = True,       # MP4-Export
    video_fps: int = 30,             # Video-Framerate
    run_config_path: str | Path | None = None,
) -> list[str]:
```

**Features**:
- ✓ Konfigurierbare Kurbelwinkel-Schrittweite (z.B. `step_deg=5.0` → 72 Frames statt 360)
- ✓ Automatische UT/OT-Erkennung via Kolbengeschwindigkeit
- ✓ Overlay-Annotation mit Kurbelwinkel-Markern
- ✓ Optionaler MP4-Export mit imageio
- ✓ Lineare Interpolation zwischen Datenpunkten
- ✓ Lazy-Loading (keine Vorabkomputation aller Frames)

**Beispiel**:
```python
from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames

paths = export_free_piston_last_ut_ot_ut_frames(
    bundle=sim_bundle,
    rows=last_cycle_data,
    output_dir="results/frames",
    step_deg=2.0,              # 180 Frames für glattes Video
    export_video=True,
    video_fps=60,
    run_config_path="config.yaml"
)
print(f"Exported: {len(paths)} files")
```

---

### 1.2 Projekt-Renderer mit Frame-Export: `render_plot_project_with_frame_export()`

**Ort**: `src/thermo0d/output/plot_layout.py`

```python
def render_plot_project_with_frame_export(
    export_rows: list[dict[str, Any]],
    plot_path: str | Path,
    output_dir: str | Path | None = None,
    prefix: str = "",
    run_config_path: str | Path | None = None,
    export_frames: bool = False,
    frame_step: int = 10,            # Jeden Xten Frame
    export_video: bool = False,
    video_fps: int = 30,
) -> tuple[list[str], list[str]]:
```

**Features**:
- ✓ YAML-basierte Plot-Konfiguration
- ✓ Batch-Frame-Generierung (configurable `frame_step`)
- ✓ Separate Ausgabeverzeichnisse für Frames
- ✓ Video-Export optional
- ✓ Speicheroptimiert durch Lazy-Rendering

---

## 2. Konfiguration (YAML)

### 2.1 Basis-Plot-Konfiguration

**Datei**: `Projekte/plot_fp.yaml` oder eigenes Config

```yaml
# Globale Plot-Einstellungen
font_family: "DejaVu Sans"
font_size: 9.0
title_size: 11.0
axis_label_size: 9.0
tick_label_size: 8.0
grid_visible: true
grid_alpha: 0.35
legend_visible: true
legend_position: "best"
tight_layout: true
default_line_width: 2.0
default_marker_size: 4.0

# Farben & Stil
figure_title_visible: true
figure_title_size: 12.0
subplot_title_visible: true

# Figures
figures:
  - title: "Zylinderdruck UT-OT-UT"
    rows: 2
    cols: 1
    subplots:
      - title: "pV-Diagramm"
        x_signal: "cylinder_0_V_m3"
        x_title: "Volumen [cm³]"
        y_axes:
          - id: "p_axis"
            title: "Druck [bar]"
            side: "left"
            color: "#111111"
        series:
          - signal_key: "cylinder_0_p_Pa"
            label: "Druck (Last Cycle)"
            axis_id: "p_axis"
            color: "#1f77b4"
            line_style: "-"
            scale_factor: 0.00001  # Pa → bar
            line_width: 2.5

      - title: "Druck vs. Kurbelwinkel"
        x_signal: "cylinder_0_theta_deg"
        x_title: "Kurbelwinkel [°]"
        y_axes:
          - id: "p_axis"
            title: "Druck [bar]"
            side: "left"
        series:
          - signal_key: "cylinder_0_p_Pa"
            label: "Druck"
            axis_id: "p_axis"
            color: "#ff7f0e"
            scale_factor: 0.00001
        events:
          - x: 0
            label: "UT-1"
            color: "#2ca02c"
            line_style: ":"
            show_label: true
          - x: 180
            label: "OT"
            color: "#d62728"
            line_style: ":"
            show_label: true
          - x: 360
            label: "UT-2"
            color: "#2ca02c"
            line_style: ":"
            show_label: true
```

### 2.2 Frame-Export-Konfiguration

**Datei**: `Projekte/export_config.yaml`

```yaml
# Frame-Export-Einstellungen (für Strobanwendungen)
export_frames:
  enabled: true
  step_deg: 5.0              # Alle 5° einen Frame
  axis_min_deg: 0.0
  axis_max_deg: 360.0
  export_video: true
  video_fps: 30              # 30 fps für flüssiges Video
  video_codec: "mp4v"        # oder "libx264"

# Oder für Hochleistungs-Rendering:
export_frames_hires:
  enabled: false
  step_deg: 1.0              # Alle 1° (360 Frames)
  export_video: true
  video_fps: 60
  resolution_multiplier: 2.0 # 2x DPI für Details
```

---

## 3. Darstellungs- und Design-Optimierungen

### 3.1 Kontrast & Lesbarkeit

**Problem**: Overlays schwer lesbar bei farbigen Bildern.

**Lösung**: Kontrastverstärkung via Matplotlib

```python
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

fig, ax = plt.subplots()
# Fette, kontrastreiche Linie
ax.plot(x, y, linewidth=3.0, color='#1f77b4')

# Text mit Outline (readability)
ax.text(x, y, "UT", fontsize=10, fontweight='bold',
        bbox=dict(boxstyle='round,pad=0.5', facecolor='white', 
                  edgecolor='black', linewidth=1.5, alpha=0.9))

# Annotationen
ax.annotate('OT-Punkt', xy=(x_ot, y_ot), 
           xytext=(10, 10), textcoords='offset points',
           fontsize=9, fontweight='bold',
           bbox=dict(facecolor='yellow', alpha=0.7),
           arrowprops=dict(arrowstyle='->', connectionstyle='arc3,rad=0', lw=2))
```

### 3.2 Farbpaletten (Farbblind-freundlich)

```python
# Empfohlen für Universalzugänglichkeit
COLORBLIND_PALETTE = {
    'blue': '#0173B2',
    'orange': '#DE8F05',
    'green': '#029E73',
    'red': '#CC78BC',
    'grey': '#CA9161',
}

# Spezifisch für UT/OT-Markierung
STROKE_COLORS = {
    'ut': '#2ca02c',     # Grün
    'ot': '#d62728',     # Rot
    'combustion': '#ff7f0e',  # Orange
    'intake': '#1f77b4',      # Blau
    'exhaust': '#9467bd',     # Violett
}
```

### 3.3 Skalierbare Schriften & Achsen

```python
import matplotlib as mpl

# Responsive Fonts
mpl.rcParams['font.size'] = 9
mpl.rcParams['axes.labelsize'] = 10
mpl.rcParams['axes.titlesize'] = 12
mpl.rcParams['xtick.labelsize'] = 8
mpl.rcParams['ytick.labelsize'] = 8
mpl.rcParams['legend.fontsize'] = 8
mpl.rcParams['figure.titlesize'] = 14

# Achsen-Format
ax.xaxis.set_major_locator(mpl.ticker.MultipleLocator(30))  # 30° Intervalle
ax.xaxis.set_minor_locator(mpl.ticker.MultipleLocator(10))  # 10° Minor-Ticks
ax.grid(True, which='major', alpha=0.5)
ax.grid(True, which='minor', alpha=0.2, linestyle=':')
```

---

## 4. Performance-Optimierungen

### 4.1 Downsampling für schnelle Vorschau

```python
import numpy as np

def downsample_data(data: np.ndarray, factor: int = 5) -> np.ndarray:
    """Reduce data points for fast preview."""
    return data[::factor]

# Vorschau (schnell, ~72 Frames @ 5° step)
export_free_piston_last_ut_ot_ut_frames(
    ..., step_deg=5.0, ...  # Fast preview
)

# Detail-Render (langsam, ~360 Frames @ 1° step)
export_free_piston_last_ut_ot_ut_frames(
    ..., step_deg=1.0, ...  # Detailed render
)
```

### 4.2 Memory-Mapping bei großen Datenmengen

```python
import numpy as np

# Große CSV als Memory-Mapped Array laden
data = np.load("results/export.npy", mmap_mode='r')
# Nur benötigte Chunks werden in RAM geladen
```

### 4.3 Parallele Preprocessing

```python
from multiprocessing import Pool
from functools import partial

def process_frame(frame_idx: int, data: dict, config: dict) -> tuple[int, Path]:
    """Process single frame (parallelizable)."""
    # Filter, normalize, interpolate
    return frame_idx, output_path

# Parallele Verarbeitung
with Pool(processes=4) as pool:
    frame_tasks = [
        (i, data, config) for i in range(0, len(data), frame_step)
    ]
    results = pool.starmap(process_frame, frame_tasks)
```

### 4.4 Effiziente Rendering-APIs

```python
# Nutze minimales matplotlib-Overhead
import matplotlib.pyplot as plt
from matplotlib.figure import Figure

# Schneller: Figure direkt ohne show()
fig = Figure(figsize=(8, 5), dpi=100)
ax = fig.subplots()
ax.plot(x, y)
fig.savefig("output.png")  # Keine plt.show()

# DPI-Optimierung
fig.savefig("output.png", dpi=150, bbox_inches='tight')  # Standard
# fig.savefig("output.png", dpi=300)  # High-res
# fig.savefig("output.png", dpi=72)   # Web
```

---

## 5. Export-Formate & Qualität

### 5.1 PNG vs. PDF/SVG

```python
# Raster (PNG) - schnell, kompakt
fig.savefig("plot.png", dpi=300, bbox_inches='tight')

# Vektor (PDF/SVG) - für Overlays & Text
fig.savefig("plot.pdf", bbox_inches='tight')
fig.savefig("plot.svg", bbox_inches='tight')

# Hybrid: Raster mit Vektor-Overlays
from matplotlib.backends.backend_pdf import PdfPages
with PdfPages("multi_page.pdf") as pdf:
    pdf.savefig(fig_image, metadata={'Title': f'Frame {i}'})
    # Nachträgliche Annotation möglich
```

### 5.2 Video-Export-Qualitäten

```python
import imageio

# Standard (H.264, MP4)
with imageio.get_writer("output.mp4", fps=30, codec='libx264') as w:
    for frame_path in frame_paths:
        w.append_data(imageio.imread(frame_path))

# High-Quality (ProRes, großer File)
with imageio.get_writer("output.mov", fps=30, codec='prores') as w:
    for frame_path in frame_paths:
        w.append_data(imageio.imread(frame_path))

# GIF (kleinere Größe, schlechtere Qualität)
with imageio.get_writer("output.gif", duration=0.1) as w:
    for frame_path in frame_paths:
        w.append_data(imageio.imread(frame_path))
```

---

## 6. Interaktive Anwendungen

### 6.1 Jupyter + ipywidgets (schnelle Iteration)

```python
import ipywidgets as widgets
import numpy as np
from IPython.display import display
from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames

# Slider für Schrittweite
step_slider = widgets.FloatSlider(min=1.0, max=10.0, step=1.0, value=5.0, description="Step [°]:")
fps_slider = widgets.IntSlider(min=10, max=120, step=10, value=30, description="FPS:")
export_btn = widgets.Button(description="Export Video")

def on_export(b):
    export_free_piston_last_ut_ot_ut_frames(
        bundle, rows, "output",
        step_deg=step_slider.value,
        video_fps=fps_slider.value,
        export_video=True
    )
    print(f"✓ Exported with step={step_slider.value}°, fps={fps_slider.value}")

export_btn.on_click(on_export)
display(step_slider, fps_slider, export_btn)
```

### 6.2 Plotly für Web-basierte Scrubbing

```python
import plotly.graph_objects as go
import plotly.express as px

# Interaktiv mit Slider
fig = px.line(df, x="theta_deg", y="p_Pa", 
              title="Cylinder Pressure vs. Crank Angle",
              hover_data={"t_s": ":.3f"})

# Add UT/OT Marker
fig.add_vline(x=0, line_dash="dash", line_color="green", annotation_text="UT-1")
fig.add_vline(x=180, line_dash="dash", line_color="red", annotation_text="OT")
fig.add_vline(x=360, line_dash="dash", line_color="green", annotation_text="UT-2")

fig.show()
```

---

## 7. Verwendungsbeispiel (vollständig)

```python
#!/usr/bin/env python3
"""
Complete stroke frame export example.
"""
from pathlib import Path
from thermo0d.app.runner import simulate
from thermo0d.output.plots import export_free_piston_last_ut_ot_ut_frames

# 1. Simulation
config_path = Path("Projekte/config.yaml")
bundle, export_rows = simulate(config_path)

# 2. Frame-Export
output_dir = Path("results/strokes/last_cycle")
frame_paths = export_free_piston_last_ut_ot_ut_frames(
    bundle=bundle,
    rows=export_rows,
    output_dir=output_dir,
    step_deg=2.0,          # 180 Frames
    axis_min_deg=0.0,
    axis_max_deg=360.0,
    export_video=True,
    video_fps=60,
    run_config_path=config_path
)

print(f"✓ Frames: {len(frame_paths)} files")
print(f"✓ Output: {output_dir}")

# 3. Optional: Batch mit verschiedenen Konfigurationen
for step_deg in [1.0, 5.0, 10.0]:
    subdir = output_dir / f"step_{int(step_deg)}deg"
    subdir.mkdir(parents=True, exist_ok=True)
    export_free_piston_last_ut_ot_ut_frames(
        bundle, export_rows, subdir,
        step_deg=step_deg, export_video=True, video_fps=30
    )
    print(f"✓ Batch completed: {step_deg}°")
```

---

## 8. Best Practices Checkliste

- [ ] **Konfiguration**: YAML-Config mit Presets anlegen
- [ ] **Datenqualität**: Invalid/NaN-Werte prüfen (siehe `valid` in `export_free_piston_last_ut_ot_ut_frames()`)
- [ ] **Speicher**: `frame_step` anpassen bei großen Datenmengen
- [ ] **Performance**: Lokale Tests mit downsampling (step_deg=10.0)
- [ ] **Annotation**: UT/OT-Marker konsistent über alle Frames
- [ ] **Farben**: Farbblind-freundliche Palette verwenden
- [ ] **Export**: DPI & Codec-Wahl nach Use-Case
- [ ] **Reproduzierbarkeit**: Config-File & CLI-Parameter speichern
- [ ] **Video**: test_fps_range mit Zielgeräten testen

---

## 9. Troubleshooting

| Problem | Lösung |
|---------|--------|
| Video zu groß | `codec='libx264'`, DPI senken, oder GIF statt MP4 |
| Frames unscharf | DPI erhöhen (150 → 300) oder Interpolation linéar → cubic |
| Langsam | `frame_step` erhöhen, oder `process_pool=True` |
| Memory-Fehler | `np.memmap()` für große Data, oder Daten in Batches laden |
| UT/OT nicht erkannt | Check velocity sign transitions & data validity |

---

## 10. API-Referenz

### `export_free_piston_last_ut_ot_ut_frames()`

```
Signatur:
  export_free_piston_last_ut_ot_ut_frames(
    bundle,                    # ModelBundle mit Geometrie
    rows,                      # CSV-Export als list[dict]
    output_dir,                # Output-Verzeichnis
    step_deg=1.0,              # Kurbelwinkel-Schritt
    axis_min_deg=0.0,
    axis_max_deg=360.0,
    export_video=True,         # MP4-Export
    video_fps=30,
    run_config_path=None
  ) → list[str]                # Pfade zu Frames + Video

Exceptions:
  - Returns empty list bei ungültigen Daten
  - ValueError: Wenn UT/OT nicht detektiert
  - IOError: Bei Schreibproblemen
```

### `render_plot_project_with_frame_export()`

```
Signatur:
  render_plot_project_with_frame_export(
    export_rows,               # CSV-Zeilen
    plot_path,                 # YAML-Plot-Config
    output_dir=None,
    prefix="",
    run_config_path=None,
    export_frames=False,       # Frame-Generierung
    frame_step=10,             # Jeden Xten Frame
    export_video=False,
    video_fps=30
  ) → tuple[list[str], list[str]]  # (plots, frames)
```

---

**Letztes Update**: 2026-04-22  
**Autor**: Optimization Guide für MotorSim V03
