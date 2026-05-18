# README_plot.md

Diese Datei beschreibt die Plot-Konfiguration für den aktuellen Stand von `thermo0d`.

## Neu in diesem Stand

Zusätzlich zu den bisherigen Plot-Parametern sind jetzt diese Optionen verfügbar:

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
- `axis_label_size`: Schriftgröße für X- und Y-Achsenbeschriftungen
- `tick_label_size`: Schriftgröße für Tick-Labels
- `title_size`: Schriftgröße für Subplot-Titel
- `figure_title_size`: Schriftgröße für den Figure-Gesamttitel
- `subplot_title_visible`: globale Freigabe für Subplot-Titel
- `figure_title_visible`: globale Freigabe für Figure-Titel

### Neue Subplot-Optionen

```yaml
subplots:
  - title: Zylinderdruck über Zeit
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

## Wählbare Stil-Presets

Im Plot-Editor sind jetzt diese Presets auswählbar:

- `Light Engineering`
- `Compact Engineering`
- `Paper`
- `Dark Engineering`
- `Dark Presentation`
- `Presentation`

Empfehlung:
- **Light Engineering**: guter Standard für Entwicklung
- **Compact Engineering**: kompakter für viele Subplots
- **Paper**: sachlich, wenig Ballast, Titel standardmäßig aus
- **Presentation**: größere Linien und Schriften
- **Dark Engineering / Dark Presentation**: dunkle Oberfläche

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

## Professionelle Grundeinstellung – Vorschlag

Für technische Standardplots empfehle ich:

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

## Für Berichte / Paper

```yaml
style:
  preset_name: Paper
  subplot_title_visible: false
  figure_title_visible: false
  axis_label_size: 10
  tick_label_size: 9
  grid_alpha: 0.45
```

## Für Präsentation

```yaml
style:
  preset_name: Presentation
  axis_label_size: 12
  tick_label_size: 11
  title_size: 15
  figure_title_size: 17
```

## Hinweis zum aktuellen Renderer

Die neuen Felder werden jetzt sowohl im Plot-Editor als auch im Batch-Renderer berücksichtigt für:

- X-Achse ab 0 im Auto-Modus
- Achsenbeschriftungsgröße
- Tick-Label-Größe
- Subplot-Titel ein/aus
- Figure-Titel ein/aus
- Figure-/Subplot-Titelgrößen
- Stil-Presets

