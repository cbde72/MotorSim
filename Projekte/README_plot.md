# README_plot.md

Diese Datei dokumentiert **alle Plot-Parameter**, die in deinem aktuellen Projektstand vorkommen oder gespeichert werden.

Wichtig ist die Unterscheidung zwischen zwei Ebenen:

1. **Plot-Datei für den eigentlichen PNG-Renderer**
   - wird von `src/thermo0d/output/plot_layout.py` eingelesen
   - daraus werden die finalen PNG-Plots erzeugt

2. **Projektdatei des Plot-Editors**
   - wird vom `plot_style_editor.py` benutzt
   - enthält zusätzliche Felder für Editor, Vorschau und Stil
   - ein Teil davon wird beim eigentlichen Batch-Rendern aktuell **noch nicht** ausgewertet

Diese README trennt deshalb sauber zwischen:
- **aktiv vom Renderer benutzt**
- **im Editor gespeichert, aber aktuell nicht oder nur teilweise benutzt**

---

## 1. Wo die Plot-Konfiguration verwendet wird

### 1.1 In der Simulations-YAML
Im normalen Simulations-Config-File wird festgelegt, **ob** geplottet wird und **welche Plot-YAMLs** benutzt werden.

Beispiel:

```yaml
postprocessing:
  plots:
    enabled: true
    source: last_cycle_uniform
    output_dir: null
    layouts:
      auto_create_defaults: true
      entries:
        - path: plot.yaml
          prefix: "std"
        - path: plot_fp.yaml
          prefix: "fp"
```

### 1.2 In der Plot-YAML selbst
Die eigentliche Plotdatei beschreibt:
- Figuren
- Subplots
- Achsen
- Datenreihen
- Events
- horizontale Linien

Beispiel:

```yaml
name: Mein Plotpaket
figures:
  - title: Zeitplots
    rows: 2
    cols: 1
    subplots:
      - title: Druck
        x_signal: t_s
        x_title: Zeit [s]
        x_limit_mode: manual
        x_min: 0.0
        x_max: 0.2
        y_axes:
          - id: ax_p
            title: Druck [bar]
            limit_mode: manual
            y_min: 0.0
            y_max: 150.0
        series:
          - signal_key: cylinder_p_Pa
            label: Zylinderdruck
            axis_id: ax_p
            color: "#111111"
            line_style: "-"
            line_width: 1.8
            scale_factor: 1.0e-5
            offset: 0.0
```

---

## 2. Parameter in der Simulations-YAML unter `postprocessing.plots`

Diese Felder sind in `src/thermo0d/config/models.py` definiert.

### `postprocessing.plots.enabled`
- Typ: `bool`
- Bedeutung: Plot-Erzeugung ein/aus.

### `postprocessing.plots.source`
- Typ: `"last_cycle_uniform" | "export_rows"`
- Bedeutung:
  - `last_cycle_uniform`: Plots aus dem gleichmäßig resampelten letzten Zyklus
  - `export_rows`: Plots direkt aus den Export-Zeilen

### `postprocessing.plots.output_dir`
- Typ: `str | null`
- Bedeutung: optionaler Zielordner für Plot-PNGs.
- Wenn `null`, nimmt der Code den Standardpfad.

### `postprocessing.plots.layouts.auto_create_defaults`
- Typ: `bool`
- Bedeutung: Standard-Plotdateien automatisch anlegen, falls sie fehlen.

### `postprocessing.plots.layouts.entries`
Liste von Plot-Dateien.

Jeder Eintrag hat:

#### `path`
- Typ: `str`
- Pflichtfeld
- Bedeutung: Pfad zur Plot-YAML.

#### `prefix`
- Typ: `str`
- Default: `""`
- Bedeutung: Präfix für den PNG-Dateinamen.

#### `enabled`
- Typ: `bool`
- Default: `true`
- Bedeutung: einzelnes Plotlayout aktiv/inaktiv.

---

## 3. Struktur der Plot-YAML

Top-Level:

```yaml
name: ...
figures:
  - ...
```

### `name`
- Typ: `str`
- Bedeutung: Projektname der Plotdatei.
- Hinweis: aktuell eher dokumentarisch; der Renderer arbeitet primär mit `figures`.

### `figures`
- Typ: Liste
- Bedeutung: Liste der zu rendernden Figures.

---

## 4. Figure-Parameter

Jeder Eintrag in `figures:` kann folgende Felder enthalten.

### Aktiv vom Renderer benutzt

#### `title`
- Typ: `str`
- Bedeutung: Figure-Titel.
- Wird auch für den PNG-Dateinamen verwendet.

#### `rows`
- Typ: `int`
- Bedeutung: Anzahl Subplot-Zeilen.
- Mindestwert praktisch `1`.

#### `cols`
- Typ: `int`
- Bedeutung: Anzahl Subplot-Spalten.
- Mindestwert praktisch `1`.

#### `subplots`
- Typ: Liste
- Bedeutung: Subplot-Definitionen.

### Im Editor gespeichert

#### `id`
- Typ: `str`
- Bedeutung: interne Editor-ID.
- Hinweis: vom finalen PNG-Renderer nicht benötigt.

---

## 5. Subplot-Parameter

Beispiel:

```yaml
subplots:
  - title: Druckverlauf
    plot_type: line
    x_signal: cylinder_theta_deg
    x_title: Kurbelwinkel [deg]
    x_unit_preset: raw
    x_scale_factor: 1.0
    x_offset: 0.0
    x_limit_mode: manual
    x_min: 0.0
    x_max: 720.0
    legend_visible: true
    legend_position: best
    show_grid: true
    y_axes: [...]
    series: [...]
    events: [...]
    y_lines: [...]
```

### Aktiv vom Renderer benutzt

#### `title`
- Typ: `str`
- Bedeutung: Titel des Subplots.

#### `x_signal`
- Typ: `str`
- Bedeutung: Signalname für die X-Achse.
- Beispiele:
  - `t_s`
  - `theta_deg`
  - `cylinder_theta_deg`
  - `free_piston_x_m` (technisch möglich, meist aber Y-Signal)

#### `x_title`
- Typ: `str`
- Bedeutung: Beschriftung der X-Achse.

#### `x_limit_mode`
- Typ: `"manual" | "data"`
- Bedeutung:
  - `manual`: benutze `x_min` und `x_max`
  - `data`: nimm Grenzen aus den Daten
- Besonderheit für Winkelplots:
  - Wenn `x_signal` auf `theta_deg` oder `...theta_deg` endet, wird eine Winkelachse erkannt.
  - Dann setzt der Code automatisch Hauptgitter auf `180°` und Nebengitter auf `60°`.

#### `x_min`
- Typ: `float`
- Bedeutung: untere X-Grenze bei `x_limit_mode: manual`.

#### `x_max`
- Typ: `float`
- Bedeutung: obere X-Grenze bei `x_limit_mode: manual`.

#### `y_axes`
- Typ: Liste
- Bedeutung: Definition der Y-Achsen.

#### `series`
- Typ: Liste
- Bedeutung: die zu zeichnenden Kurven.

#### `events`
- Typ: Liste
- Bedeutung: vertikale Ereignislinien, z. B. OT, UT, IVO, EVC, SOC, EOC.

#### `y_lines`
- Typ: Liste
- Bedeutung: horizontale Linien über die gesamte X-Achse.

### Im Editor gespeichert, aber aktuell vom finalen Renderer nicht oder nur indirekt benutzt

#### `plot_type`
- Typ: `str`
- Typischer Wert: `line`
- Hinweis: aktuell rendert der Batch-Renderer faktisch Linienplots.

#### `x_unit_preset`
- Typ: `str`
- Typische Werte: `raw`, `deg`
- Hinweis: im finalen Renderer derzeit nicht aktiv ausgewertet.

#### `x_scale_factor`
- Typ: `float`
- Hinweis: wird im aktuellen Batch-Renderer nicht angewendet.

#### `x_offset`
- Typ: `float`
- Hinweis: wird im aktuellen Batch-Renderer nicht angewendet.

#### `legend_visible`
- Typ: `bool`
- Hinweis: der Renderer zeigt die Legende aktuell automatisch, sobald Serien vorhanden sind.

#### `legend_position`
- Typ: `str`
- Hinweis: der Renderer verwendet aktuell fest `loc="best"`.

#### `show_grid`
- Typ: `bool`
- Hinweis: der Renderer aktiviert das Grid aktuell pauschal.

#### `id`
- Typ: `str`
- Bedeutung: interne Editor-ID.

---

## 6. Y-Achsen-Parameter `y_axes`

Beispiel:

```yaml
y_axes:
  - id: ax_p
    title: Druck [bar]
    side: left
    color: "#111111"
    visible: true
    spine_offset: 0.0
    limit_mode: manual
    y_min: 0.0
    y_max: 150.0
    tick_step: 10.0
    minor_tick_step: 5.0
    major_grid: true
    minor_grid: false
```

### Aktiv vom Renderer benutzt

#### `id`
- Typ: `str`
- Bedeutung: eindeutige Achsen-ID.
- Wichtig: `series.axis_id` und `y_lines.axis_id` referenzieren diese ID.

#### `title`
- Typ: `str`
- Bedeutung: Achsentitel.

#### `limit_mode`
- Typ: `"manual" | "data"`
- Bedeutung:
  - `manual`: benutze `y_min` und `y_max`
  - `data`: automatische Skalierung durch Matplotlib

#### `y_min`
- Typ: `float`
- Bedeutung: untere Achsgrenze bei `manual`.

#### `y_max`
- Typ: `float`
- Bedeutung: obere Achsgrenze bei `manual`.

#### `tick_step`
- Typ: `float`
- Bedeutung: Abstand der Hauptticks.
- Wirkung nur, wenn `> 0`.

#### `minor_tick_step`
- Typ: `float`
- Bedeutung: Abstand der Nebenticks.
- Wirkung nur, wenn `> 0`.

### Im Editor gespeichert, aber aktuell vom finalen Renderer nicht vollständig ausgewertet

#### `side`
- Typ: `"left" | "right"`
- Hinweis: im finalen Renderer zählt aktuell vor allem die **Reihenfolge** in `y_axes`.
  - erste Achse = links
  - zweite und weitere Achsen = rechts

#### `color`
- Typ: `str`
- Bedeutung: Achsenfarbe im Editor/Preview.
- Hinweis: im Batch-Renderer derzeit nicht explizit auf Ticks/Label gelegt.

#### `visible`
- Typ: `bool`
- Hinweis: aktuell nicht als echtes Ein/Aus im finalen Renderer umgesetzt.

#### `spine_offset`
- Typ: `float`
- Hinweis: der Batch-Renderer benutzt für zusätzliche rechte Achsen derzeit einen festen Outward-Abstand.

#### `major_grid`
- Typ: `bool`
- Hinweis: im finalen Renderer nicht separat ausgewertet.

#### `minor_grid`
- Typ: `bool`
- Hinweis: im finalen Renderer nicht separat ausgewertet.

---

## 7. Serien-Parameter `series`

Beispiel:

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
    unit_preset: raw
    scale_factor: 1.0e-5
    offset: 0.0
    series_type: line
```

### Aktiv vom Renderer benutzt

#### `signal_key`
- Typ: `str`
- Pflichtfeld in der Praxis
- Bedeutung: Name der CSV-/Export-Spalte.
- Beispiel:
  - `cylinder_p_Pa`
  - `cylinder_T_K`
  - `cylinder_added_energy_W`
  - `cylinder_added_energy_cycle_J`
  - `free_piston_v_m_per_s`

#### `label`
- Typ: `str`
- Bedeutung: Legendentext.
- Wenn leer, nimmt der Renderer den `signal_key`.

#### `axis_id`
- Typ: `str`
- Bedeutung: Zuordnung auf eine Y-Achse aus `y_axes`.

#### `color`
- Typ: `str`
- Bedeutung: Linienfarbe.

#### `line_style`
- Typ: `str`
- Typische Werte:
  - `"-"`
  - `"--"`
  - `":"`
  - `"-."`

#### `line_width`
- Typ: `float`
- Bedeutung: Liniendicke.

#### `scale_factor`
- Typ: `float`
- Bedeutung: Skaliert den Rohwert vor dem Plotten.
- Beispiele:
  - Pa → bar: `1.0e-5`
  - m³ → cm³: `1.0e6`
  - kg → mg: `1.0e6`
  - m → mm: `1000.0`

#### `offset`
- Typ: `float`
- Bedeutung: additiver Offset nach der Skalierung.
- Formel im Renderer:

```text
plot_value = raw_value * scale_factor + offset
```

### Im Editor gespeichert, aber aktuell vom finalen Renderer nicht benutzt

#### `visible`
- Typ: `bool`
- Hinweis: im finalen Renderer derzeit nicht als Filter umgesetzt.

#### `marker`
- Typ: `str`
- Hinweis: Batch-Renderer benutzt aktuell keine Marker.

#### `marker_size`
- Typ: `float`
- Hinweis: aktuell nicht benutzt.

#### `unit_preset`
- Typ: `str`
- Typisch: `raw`
- Hinweis: aktuell nicht benutzt.

#### `series_type`
- Typ: `str`
- Typisch: `line`
- Hinweis: aktuell rendert der Batch-Renderer Linien.

#### `id`
- Typ: `str`
- Bedeutung: interne Editor-ID.

---

## 8. Event-Parameter `events`

Events zeichnen **vertikale Linien**.

Beispiel:

```yaml
events:
  - x: 360.0
    label: OT
    color: "#667085"
    line_style: ":"
    line_width: 1.0
    alpha: 0.9
    visible: true
    show_label: true
    label_rotation: 90.0
    label_font_size: 7.0
    label_bg_color: "#ffffff"
    label_bg_alpha: 0.8
    label_border_color: none
    label_y: 0.98
    label_ha: right
    label_va: top
```

### Aktiv vom Renderer benutzt

#### `x`
- Typ: `float`
- Bedeutung: Position der vertikalen Linie.

#### `label`
- Typ: `str`
- Bedeutung: Ereignistext.

#### `color`
- Typ: `str`
- Bedeutung: Linien- und Textfarbe.

#### `line_style`
- Typ: `str`
- Bedeutung: Linienstil.

#### `line_width`
- Typ: `float`
- Bedeutung: Liniendicke.

#### `alpha`
- Typ: `float`
- Bedeutung: Transparenz von `0.0` bis `1.0`.

#### `visible`
- Typ: `bool`
- Bedeutung: Event anzeigen oder ausblenden.

#### `show_label`
- Typ: `bool`
- Bedeutung: Event-Label anzeigen oder nicht.

#### `label_rotation`
- Typ: `float`
- Bedeutung: Textrotation.

#### `label_font_size`
- Typ: `float`
- Bedeutung: Schriftgröße.

#### `label_bg_color`
- Typ: `str`
- Bedeutung: Hintergrundfarbe der Label-Box.

#### `label_bg_alpha`
- Typ: `float`
- Bedeutung: Transparenz der Label-Box.

#### `label_border_color`
- Typ: `str`
- Bedeutung: Randfarbe der Label-Box.

#### `label_y`
- Typ: `float`
- Bedeutung: vertikale Position des Labels in Achsen-Koordinaten.

#### `label_ha`
- Typ: `str`
- Bedeutung: horizontale Ausrichtung, z. B. `left`, `center`, `right`.

#### `label_va`
- Typ: `str`
- Bedeutung: vertikale Ausrichtung, z. B. `top`, `center`, `bottom`.

### Im Editor gespeichert, aber für das finale Rendern nur informativ

#### `source`
- Typ: `str`
- Beispiele: `manual`, `auto`

#### `source_note`
- Typ: `str`

#### `locked`
- Typ: `bool`

#### `event_type`
- Typ: `str`
- Beispiele: `custom`, `reference`, `valve`, `combustion`

#### `id`
- Typ: `str`
- interne Editor-ID

---

## 9. Horizontale Linien `y_lines`

Diese Linien gehen über die ganze X-Achse.

Beispiel:

```yaml
y_lines:
  - y: 54.0
    axis_id: ax_p
    label: Grenze oben
    color: "#cc0000"
    line_style: "--"
    line_width: 1.0
    alpha: 0.9
    visible: true
    show_label: true
    label_x: 0.99
    label_position: above
    label_offset_pt: 3.0
    label_ha: right
    label_font_size: 8.0
    label_bg_color: "#ffffff"
    label_bg_alpha: 0.75
    label_border_color: none
```

### Aktiv vom Renderer benutzt

#### `y`
- Typ: `float`
- Bedeutung: Y-Wert der Linie.

#### `axis_id`
- Typ: `str`
- Bedeutung: Auf welche Y-Achse sich die Linie bezieht.
- Wenn leer, wird die erste Y-Achse verwendet.

#### `label`
- Typ: `str`
- Bedeutung: Text an der Linie.

#### `color`
- Typ: `str`
- Bedeutung: Linien- und Label-Farbe.

#### `line_style`
- Typ: `str`
- Bedeutung: Linienstil.

#### `line_width`
- Typ: `float`
- Bedeutung: Liniendicke.

#### `alpha`
- Typ: `float`
- Bedeutung: Transparenz.

#### `visible`
- Typ: `bool`
- Bedeutung: anzeigen oder nicht.

#### `show_label`
- Typ: `bool`
- Bedeutung: Label anzeigen oder nicht.

#### `label_x`
- Typ: `float`
- Bereich: typischerweise `0.0 ... 1.0`
- Bedeutung: X-Position des Labels in Achsenkoordinaten.
- `0.0` = links, `1.0` = rechts.

#### `label_position`
- Typ: `"above" | "below" | "center"`
- Bedeutung: Position des Labels relativ zur Linie.

#### `label_offset_pt`
- Typ: `float`
- Bedeutung: Abstand des Labels zur Linie in Punkt.

#### `label_ha`
- Typ: `str`
- Bedeutung: horizontale Textausrichtung.

#### `label_font_size`
- Typ: `float`
- Bedeutung: Schriftgröße.

#### `label_bg_color`
- Typ: `str`
- Bedeutung: Hintergrundfarbe der Box.

#### `label_bg_alpha`
- Typ: `float`
- Bedeutung: Transparenz der Box.

#### `label_border_color`
- Typ: `str`
- Bedeutung: Randfarbe der Box.

### Im Editor gespeichert, aber aktuell vom finalen Renderer nicht benutzt

#### `label_va`
- Typ: `str`
- Hinweis: im aktuellen Renderer wird die vertikale Ausrichtung aus `label_position` abgeleitet.

#### `id`
- Typ: `str`
- interne Editor-ID

---

## 10. Projektweite Editor-Felder

Wenn du eine komplette Projektdatei aus dem Plot-Editor speicherst, können zusätzlich diese Felder auftauchen:

```yaml
name: ...
figures: ...
style: ...
config_path: ...
signals_path: ...
preview_csv_path: ...
selected_cylinder: ...
notes: ...
```

### `style`
Enthält globale Stilvorgaben des Editors, z. B.:
- `preset_name`
- `background_color`
- `axes_facecolor`
- `text_color`
- `grid_color`
- `legend_facecolor`
- `legend_edgecolor`
- `default_line_width`
- `default_marker_size`
- `font_family`
- `font_size`
- `title_size`
- `grid_visible`
- `grid_alpha`
- `legend_visible`
- `legend_position`

Hinweis:
- diese Stilinformationen sind für den **Plot-Editor und dessen Preview** nützlich
- der aktuelle Batch-Renderer in `plot_layout.py` benutzt diesen `style`-Block **nicht direkt**

### `config_path`
- zuletzt geladene Simulations-Config im Editor

### `signals_path`
- Pfad zur Signal-Katalog-Datei

### `preview_csv_path`
- zuletzt geladene CSV für die Preview

### `selected_cylinder`
- aktuell ausgewählter Zylinder im Editor

### `notes`
- freie Notizen

---

## 11. Verhalten und Grenzen des aktuellen Renderers

Das ist wichtig, damit die Plot-YAML realistisch benutzt wird.

### 11.1 Was aktuell sicher funktioniert
- mehrere Figures
- `rows` / `cols`
- mehrere Subplots
- mehrere Y-Achsen
- vertikale Events
- horizontale Linien `y_lines`
- manuelle und datengetriebene Achsengrenzen
- Skalierung über `scale_factor`
- Offset über `offset`
- Winkelplots mit automatischem 180°/60°-Raster

### 11.2 Was aktuell nur gespeichert wird, aber beim finalen Rendern noch nicht vollständig wirkt
- `style`
- `x_scale_factor`
- `x_offset`
- `legend_visible`
- `legend_position`
- `show_grid`
- `marker`
- `marker_size`
- `unit_preset`
- `series_type`
- `axis.side` als echte Logik
- `axis.spine_offset`
- `axis.visible`
- `axis.color` als Tick-/Labelsteuerung
- `major_grid` / `minor_grid`

### 11.3 Mehrere Y-Achsen
Der Renderer behandelt sie aktuell praktisch so:
- erste Y-Achse = links
- zweite Y-Achse = rechts
- dritte und weitere Y-Achsen = weitere rechte Achsen nach außen verschoben

Das heißt:
- die **Reihenfolge** in `y_axes` ist aktuell wichtiger als `side`

### 11.4 Keine harte Schema-Validierung der Plot-YAML
Die Plotdatei wird aktuell per `yaml.safe_load(...)` geladen.
Das bedeutet:
- unbekannte Felder führen nicht automatisch zu einem Fehler
- falsch geschriebene Keys können still ignoriert werden

Darum ist es sinnvoll, sich an die hier dokumentierten Namen zu halten.

---

## 12. Vollständiges Beispiel

```yaml
name: Beispiel Plotpaket
figures:
  - title: Free Piston Übersicht
    rows: 3
    cols: 1
    subplots:
      - title: Druck und Energie
        plot_type: line
        x_signal: t_s
        x_title: Zeit [s]
        x_limit_mode: manual
        x_min: 0.0
        x_max: 0.25
        legend_visible: true
        legend_position: best
        show_grid: true
        y_axes:
          - id: ax_p
            title: Druck [bar]
            side: left
            limit_mode: manual
            y_min: 0.0
            y_max: 120.0
            tick_step: 10.0
            minor_tick_step: 5.0
          - id: ax_q
            title: Q_add [W]
            side: right
            limit_mode: data
        series:
          - signal_key: cylinder_p_Pa
            label: Zylinderdruck
            axis_id: ax_p
            color: "#111111"
            line_style: "-"
            line_width: 1.8
            scale_factor: 1.0e-5
            offset: 0.0
          - signal_key: cylinder_added_energy_W
            label: Verbrennungsleistung
            axis_id: ax_q
            color: "#d97706"
            line_style: "-"
            line_width: 1.5
            scale_factor: 1.0
            offset: 0.0
        events:
          - x: 0.10
            label: SOC
            color: "#f79009"
            line_style: "--"
            line_width: 1.0
            alpha: 0.9
            visible: true
            show_label: true
            label_rotation: 90.0
            label_font_size: 7.0
            label_bg_color: "#ffffff"
            label_bg_alpha: 0.8
            label_border_color: none
            label_y: 0.98
            label_ha: right
            label_va: top
        y_lines:
          - y: 54.0
            axis_id: ax_p
            label: Grenzwert oben
            color: "#cc0000"
            line_style: "--"
            line_width: 1.0
            alpha: 0.9
            visible: true
            show_label: true
            label_x: 0.99
            label_position: above
            label_offset_pt: 3.0
            label_ha: right
            label_font_size: 8.0
            label_bg_color: "#ffffff"
            label_bg_alpha: 0.75
            label_border_color: none

      - title: Integrierte Energie
        x_signal: t_s
        x_title: Zeit [s]
        x_limit_mode: manual
        x_min: 0.0
        x_max: 0.25
        y_axes:
          - id: ax_e
            title: Energie [J]
            limit_mode: data
        series:
          - signal_key: cylinder_added_energy_cycle_J
            label: Zugeführte Energie kumuliert
            axis_id: ax_e
            color: "#111111"
            line_style: "-"
            line_width: 1.8
            scale_factor: 1.0
            offset: 0.0

      - title: Lambda und Massen
        x_signal: t_s
        x_title: Zeit [s]
        x_limit_mode: manual
        x_min: 0.0
        x_max: 0.25
        y_axes:
          - id: ax_lam
            title: Lambda [-]
            limit_mode: data
          - id: ax_mass
            title: Masse [mg]
            limit_mode: data
        series:
          - signal_key: cylinder_lambda
            label: Lambda
            axis_id: ax_lam
            color: "#175cd3"
            line_style: "-"
            line_width: 1.8
            scale_factor: 1.0
            offset: 0.0
          - signal_key: cylinder_combustion_air_mass_latched_kg
            label: Luftmasse bei Verbrennungsstart
            axis_id: ax_mass
            color: "#12b76a"
            line_style: "--"
            line_width: 1.5
            scale_factor: 1.0e6
            offset: 0.0
          - signal_key: cylinder_combustion_fuel_mass_latched_kg
            label: Kraftstoffmasse bei Verbrennungsstart
            axis_id: ax_mass
            color: "#b42318"
            line_style: "--"
            line_width: 1.5
            scale_factor: 1.0e6
            offset: 0.0
```

---

## 13. Empfohlene Praxis

Für robuste Plotdateien in deinem aktuellen Stand:

1. Nutze für die X-Achse klar `t_s` oder `...theta_deg`.
2. Weise jede Serie immer explizit einer `axis_id` zu.
3. Arbeite Einheiten über `scale_factor`, nicht über freie Umdeutung im Titel.
4. Nutze `x_limit_mode: manual`, wenn du reproduzierbare Grenzen willst.
5. Nutze `y_lines`, wenn Grenzwerte oder Sollwerte sichtbar sein sollen.
6. Verlasse dich beim Batch-Renderer aktuell nicht auf Editor-Felder wie `style`, `marker`, `legend_position` oder `x_offset`.

---

## 14. Praktische Signalbeispiele für dein Projekt

Typische Signale, die du oft plotten wirst:

### Zeit / Winkel
- `t_s`
- `theta_deg`
- `cylinder_theta_deg`

### Zylinderzustand
- `cylinder_p_Pa`
- `cylinder_T_K`
- `cylinder_V_m3`
- `cylinder_m_kg`
- `cylinder_U_J`

### Energie
- `cylinder_added_energy_W`
- `cylinder_added_energy_cycle_J`
- `cylinder_wall_heat_W`
- `cylinder_wall_heat_cycle_J`
- `cylinder_piston_work_W`
- `cylinder_piston_work_cycle_J`
- `cylinder_enthalpy_in_cycle_J`
- `cylinder_enthalpy_out_cycle_J`
- `cylinder_energy_balance_residual_J`

### Verbrennung / Gemisch
- `cylinder_lambda`
- `cylinder_combustion_air_mass_latched_kg`
- `cylinder_combustion_fuel_mass_latched_kg`
- `cylinder_combustion_energy_latched_J`

### Free Piston
- `free_piston_x_m`
- `free_piston_v_m_per_s`
- `free_piston_a_m_per_s2`
- `free_piston_F_gas_N`
- `free_piston_F_bounce_N`
- `free_piston_F_friction_N`
- `free_piston_F_load_N`
- `free_piston_F_net_N`
- `bounce_pressure_Pa`
- `bounce_volume_m3`

---

## 15. Kurzfassung

Für den eigentlichen Renderer sind die wichtigsten Felder:

- `figures[].title`
- `figures[].rows`
- `figures[].cols`
- `figures[].subplots[]`
- `subplots[].x_signal`
- `subplots[].x_title`
- `subplots[].x_limit_mode`
- `subplots[].x_min`
- `subplots[].x_max`
- `subplots[].y_axes[]`
- `subplots[].series[]`
- `subplots[].events[]`
- `subplots[].y_lines[]`
- `y_axes[].id`
- `y_axes[].title`
- `y_axes[].limit_mode`
- `y_axes[].y_min`
- `y_axes[].y_max`
- `y_axes[].tick_step`
- `y_axes[].minor_tick_step`
- `series[].signal_key`
- `series[].label`
- `series[].axis_id`
- `series[].color`
- `series[].line_style`
- `series[].line_width`
- `series[].scale_factor`
- `series[].offset`

Alles andere kann sinnvoll sein, stammt aber teilweise aus dem Editor und wird aktuell noch nicht vollständig vom finalen Plot-Renderer umgesetzt.
