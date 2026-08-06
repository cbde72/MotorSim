# Plot-Konfiguration

Diese Referenz beschreibt die aktuell von `thermo0d.output.plot_layout` ausgewertete
Plot-YAML. Sie gilt für Plotdateien unter beispielsweise
`Projekte/variants/plot_total` und `Projekte/variants/plot_cycle`.

## Vollständiges Grundgerüst

```yaml
name: Beispielprojekt
style_sheet: ../../plot_style_sheet.yaml

style:
  font_family: DejaVu Sans
  font_size: 11.0
  axis_label_size: 13.0
  tick_label_size: 10.0
  title_size: 12.0
  figure_title_size: 14.0
  subplot_title_visible: true
  figure_title_visible: true
  grid_visible: true
  grid_alpha: 0.30
  legend_visible: true
  legend_position: best
  tight_layout: true
  default_line_width: 1.2
  default_marker_size: 4.0

figures:
- title: beispiel_figure
  rows: 1
  cols: 1
  subplots:
  - title: Beispiel
    plot_type: line
    x_signal: t_s
    x_title: Time [s]
    x_scale_factor: 1.0
    x_offset: 0.0
    x_limit_mode: auto
    x_start_at_zero: true
    x_axis_position: bottom

    y_axes:
    - id: ax_y
      title: Value
      side: left
      scale: linear
      limit_mode: auto
      tick_step: 0.0
      minor_tick_step: 0.0

    y_lines: []
    x_lines: []
    events: []

    series:
    - signal_key: example_signal
      label: Example
      axis_id: ax_y
      color: '#175CD3'
      line_style: '-'
      line_width: 1.2
      marker_size: 4.0
      scale_factor: 1.0
      offset: 0.0

    text_box:
      enabled: false
```

## Oberste Ebene

| Feld | Typ | Bedeutung |
|---|---|---|
| `name` | String | Name des Plotprojekts. Wird aktuell nicht als Diagrammtitel verwendet. |
| `style_sheet` | Pfad | Externe YAML mit einem `style`-Block. Relative Pfade werden relativ zur Plot-YAML aufgelöst. |
| `stylesheet` | Pfad | Alternative Schreibweise für `style_sheet`. |
| `style` | Mapping | Lokale Stilwerte. Diese überschreiben das Stylesheet. |
| `figures` | Liste | Eine oder mehrere auszugebende Abbildungen. |

Die Reihenfolge der Stilauflösung ist:

1. interne Standardwerte,
2. `style_sheet`,
3. lokaler `style`-Block.

## `style`

```yaml
style:
  preset_name: Light Engineering
  font_family: DejaVu Sans
  font_size: 11.0
  axis_label_size: 13.0
  tick_label_size: 10.0
  title_size: 12.0
  figure_title_size: 14.0
  subplot_title_visible: true
  figure_title_visible: true
  grid_visible: true
  grid_alpha: 0.30
  legend_visible: true
  legend_position: best
  tight_layout: true
  default_line_width: 1.2
  default_marker_size: 4.0
```

| Feld | Standard | Bedeutung |
|---|---:|---|
| `preset_name` | `Light Engineering` | Metadatum; hat derzeit keine eigene Renderlogik. |
| `font_family` | `DejaVu Sans` | Schriftfamilie. |
| `font_size` | `8` | Allgemeine Schriftgröße. |
| `axis_label_size` | `8` | Schriftgröße der X- und Y-Achsentitel. |
| `tick_label_size` | `8` | Schriftgröße der Achsenwerte und der Legende. |
| `title_size` | `9` | Schriftgröße der Subplot-Titel. |
| `figure_title_size` | `10` | Schriftgröße des Figure-Titels. |
| `subplot_title_visible` | `true` | Subplot-Titel ein-/ausblenden. |
| `figure_title_visible` | `true` | Übergeordneten Figure-Titel ein-/ausblenden. |
| `grid_visible` | `true` | Rasterlinien ein-/ausblenden. |
| `grid_alpha` | `0.3` | Transparenz der Rasterlinien von `0` bis `1`. |
| `legend_visible` | `true` | Legende ein-/ausblenden. |
| `legend_position` | `best` | Matplotlib-Position, z. B. `best`, `upper right`, `upper left`, `lower right`, `lower left`, `center`. |
| `tight_layout` | `true` | Automatische Abstandsoptimierung. |
| `default_line_width` | `1.8` | Standardbreite, wenn eine Serie keine `line_width` angibt. |
| `default_marker_size` | `4` | Markergröße; aktuell wird kein Marker-Typ aus der YAML an `plot()` übergeben. |

## `figures`

```yaml
figures:
- title: pressure_and_temperature
  rows: 2
  cols: 1
  subplots: []
```

| Feld | Standard | Bedeutung |
|---|---:|---|
| `title` | `Figure N` | Figure-Titel und Bestandteil des Ausgabedateinamens. |
| `rows` | `1` | Anzahl Subplot-Zeilen, mindestens 1. |
| `cols` | `1` | Anzahl Subplot-Spalten, mindestens 1. |
| `subplots` | `[]` | Subplot-Liste in zeilenweiser Reihenfolge. |

Die feste Figure-Größe beträgt aktuell ungefähr `7.0 × cols` Zoll und
`3.8 × rows` Zoll bei 150 dpi. Dafür existiert noch kein YAML-Feld.

## Subplot-Grundfelder

```yaml
- title: Pressure
  plot_type: line
  x_signal: t_s
  x_title: Time [s]
  x_scale_factor: 1.0
  x_offset: 0.0
  x_limit_mode: auto
  x_start_at_zero: true
  x_axis_position: bottom
  y_axes: []
  y_lines: []
  events: []
  series: []
```

| Feld | Standard | Bedeutung |
|---|---:|---|
| `title` | `Subplot N` | Subplot-Titel. |
| `plot_type` | – | Üblicher Wert `line`; aktuell wird unabhängig davon als Linienplot gerendert. |
| `x_signal` | `t_s` | Signal für die X-Achse. |
| `x_title` | Wert von `x_signal` | Beschriftung der X-Achse. |
| `x_scale_factor` | `1.0` | Multiplikator der X-Werte. |
| `x_offset` | `0.0` | Offset nach der X-Skalierung. |
| `x_limit_mode` | `data` | `auto`/`data` oder `manual`. |
| `x_start_at_zero` | `false` | Bei automatischer normaler X-Achse die linke Grenze auf null setzen. |
| `x_axis_position` | `bottom` | `bottom` wird explizit unterstützt. |
| `y_axes` | automatisch | Definition einer oder mehrerer Y-Achsen. |
| `series` | `[]` | Darzustellende Signale. |
| `y_lines` | `[]` | Horizontale Referenzlinien. |
| `x_lines` | `[]` | Vertikale Referenzlinien mit denselben Formatoptionen wie `y_lines`. |
| `events` | `[]` | Vertikale Ereignislinien. |
| `text_box` | – | Kennwert- oder README-Infobox. |
| `show_title` | – | Kommt in bestehenden Dateien vor, wird aktuell aber nicht ausgewertet; maßgeblich ist `style.subplot_title_visible`. |

Für X-Werte gilt:

```text
x_plot = x_signal * x_scale_factor + x_offset
```

## Normale X-Achse

Automatische Datengrenzen:

```yaml
x_limit_mode: auto
```

Automatisch, aber bei null beginnen:

```yaml
x_limit_mode: auto
x_start_at_zero: true
```

Manuell:

```yaml
x_limit_mode: manual
x_min: 0.0
x_max: 1.0
```

## Winkel-X-Achse

Eine besondere Winkelbehandlung wird aktiviert, wenn `x_signal` einen der
folgenden Werte besitzt oder auf `_theta_deg` endet:

- `theta_deg`
- `theta_local_deg`
- `crank_angle_deg`
- `free_piston_crank_angle_deg`
- `*_theta_deg`

```yaml
x_signal: theta_deg
x_title: Mechanical angle [deg]
x_limit_mode: manual
x_min: -9.0
x_max: 9.0
x_tick_step: 1.0
x_minor_tick_step: 0.5
x_axis_position: bottom
```

| Feld | Alternative | Bedeutung |
|---|---|---|
| `x_tick_step` | `x_major_tick_step` | Abstand der Hauptticks. |
| `x_minor_tick_step` | – | Abstand der Nebenticks. |
| `x_tick_label_mode` | – | `ut_ot_ut` oder `last_ut_ot_ut` beschriftet Grenzen als UT und null als OT. |

Ist kein `x_minor_tick_step` angegeben und der Hauptschritt kleiner als 180°, wird
der Hauptschritt derzeit zugleich als Minor-Locator gesetzt.

## Y-Achsen

```yaml
y_axes:
- id: ax_pressure
  title: Pressure [bar]
  side: left
  spine_offset: 0.0
  label_pad: 8.0
  tick_label_pad: 4.0
  color: '#111111'
  scale: linear
  limit_mode: manual
  y_min: 0.0
  y_max: 100.0
  tick_step: 10.0
  minor_tick_step: 2.0

- id: ax_temperature
  title: Temperature [K]
  side: right
  spine_offset: 0.12
  label_pad: 10.0
  tick_label_pad: 5.0
  limit_mode: auto
```

| Feld | Standard | Bedeutung |
|---|---:|---|
| `id` | `yN` | Eindeutige ID zur Zuordnung der Serien. |
| `title` | leer | Beschriftung der Y-Achse. |
| `side` | – | Seite der Achse: `left` oder `right`. |
| `spine_offset` | `0` | Position relativ zum Plotbereich. Rechts gilt `1 + spine_offset`, links `-spine_offset`; `0.12` entspricht 12 % der Achsenbreite Abstand. |
| `label_pad` | `4` | Abstand des Y-Achsentitels von der Achse in Punkten. |
| `tick_label_pad` | `3.5` | Abstand der numerischen Tick-Beschriftungen von der Achsenlinie in Punkten. |
| `color` | `#111111` | Farbe von Achsenlinie, Achsentitel und Tick-Beschriftungen. |
| `scale` | `linear` | `linear`, `log` oder `logarithmic`. |
| `y_scale` | – | Alternative Schreibweise für `scale`. |
| `limit_mode` | `data` | `auto`/`data` oder `manual`. |
| `y_min` | `0` | Untergrenze bei `manual`. |
| `y_max` | `y_min + 1` | Obergrenze bei `manual`. |
| `tick_step` | `0` | Haupttickabstand; `0` bedeutet automatisch. |
| `minor_tick_step` | `0` | Nebentickabstand; `0` bedeutet keine explizite Vorgabe. |

Hinweise:

- `min` und `max` kommen in älteren YAMLs vor, werden aber nicht für die Grenzen ausgewertet.
- `axis_label_size` und `tick_label_size` innerhalb eines Y-Achsen-Eintrags werden aktuell nicht angewendet. Schriftgrößen gehören in `style`.
- Bei logarithmischer Skalierung müssen die geplotteten Werte und manuellen Grenzen positiv sein.
- Mehrere Y-Achsen können mit `side` und `spine_offset` unabhängig links oder rechts positioniert werden.
- Feste Dezimalstellen, wissenschaftliche Tickformatierung, Achseninvertierung und `symlog` sind derzeit nicht konfigurierbar.

## Serien

```yaml
series:
- signal_key: cylinder_1_p_Pa
  label: Cylinder 1
  axis_id: ax_pressure
  color: '#D92D20'
  line_style: '-'
  line_width: 1.2
  marker_size: 4.0
  scale_factor: 1.0e-5
  offset: 0.0
  hide_before_positive_signal: cylinder_1_combustion_active_0to1
  hide_threshold: 0.0
  show_while_positive_signal: cylinder_1_combustion_active_0to1
  active_threshold: 0.0
```

| Feld | Standard | Bedeutung |
|---|---:|---|
| `signal_key` | leer | Exakter Schlüssel des Signals. Pflicht für eine sinnvolle Serie. |
| `label` | `signal_key` | Legendentext. |
| `axis_id` | erste Y-Achse | Zielachse. |
| `color` | `#111111` | Matplotlib-Farbe, z. B. Hexcode oder Farbname. |
| `line_style` | `-` | Üblich: `-`, `--`, `-.`, `:`, `solid`, `dashed`, `dashdot`, `dotted`. |
| `line_width` | Stilstandard | Linienbreite. |
| `marker_size` | Stilstandard | Markergröße; ohne Marker-Unterstützung derzeit meist ohne sichtbare Wirkung. |
| `scale_factor` | `1.0` | Multiplikator. |
| `offset` | `0.0` | Offset nach der Multiplikation. |
| `hide_before_positive_signal` | leer | Blendet Werte aus, bis ein anderes Signal erstmals über `hide_threshold` liegt. |
| `hide_threshold` | `0.0` | Schwelle für `hide_before_positive_signal`. |
| `show_while_positive_signal` | leer | Zeigt Werte nur, solange das Steuersignal über `active_threshold` liegt. |
| `active_threshold` | `0.0` | Schwelle für `show_while_positive_signal`. |

Für Serienwerte gilt:

```text
y_plot = signal * scale_factor + offset
```

Typische Umrechnungen:

```yaml
# Pa -> bar
scale_factor: 1.0e-5

# m -> mm
scale_factor: 1000.0

# rad -> deg
scale_factor: 57.29577951308232
```

Der häufig vorhandene Eintrag `unit_preset: raw` wird vom aktuellen Renderer
nicht ausgewertet. Auch ein Serienfeld `alpha` wird derzeit nicht an die Linie
weitergegeben.

## Horizontale Referenzlinien (`y_lines`)

```yaml
y_lines:
- y: 50.0
  axis_id: ax_pressure
  label: Limit
  visible: true
  show_label: true
  color: '#D92D20'
  line_style: '--'
  line_width: 1.0
  alpha: 0.9
  label_x: 0.98
  label_font_size: 9.0
  label_bg_color: '#ffffff'
  label_border_color: none
  label_bg_alpha: 0.8
  label_ha: right
  label_va: bottom
```

| Feld | Standard | Bedeutung |
|---|---:|---|
| `y` | `0` | Y-Position. |
| `axis_id` | erste Y-Achse | Achse, deren Skalierung verwendet wird. |
| `label` | leer | Beschriftung. |
| `visible` | `true` | Linie ein-/ausblenden. |
| `show_label` | `true` | Text ein-/ausblenden. |
| `color` | `#667085` | Linien- und Textfarbe. |
| `line_style` | `--` | Linienstil. |
| `line_width` | `1.0` | Linienbreite. |
| `alpha` | `0.9` | Linientransparenz von 0 bis 1. |
| `label_x` | `0.99` | Relative horizontale Textposition von 0 bis 1. |
| `label_font_size` | `8` | Textgröße. |
| `label_bg_color` | `#ffffff` | Hintergrundfarbe. |
| `label_border_color` | `none` | Rahmenfarbe. |
| `label_bg_alpha` | abgeleitet | Transparenz des Texthintergrunds. |
| `label_ha` | `right` | Horizontale Ausrichtung: `left`, `center`, `right`. |
| `label_va` | `bottom` | Vertikale Ausrichtung: `bottom`, `center`, `top`. |

Ältere Felder wie `label_position` und `label_offset_pt` werden von der aktuellen
Renderfunktion nicht ausgewertet.

## Vertikale Referenzlinien (`x_lines`)

`x_lines` ist das vertikale Gegenstück zu `y_lines`. Die Linie verwendet die
X-Skalierung des Subplots. Die Beschriftungsposition wird mit `label_y` relativ
zur Achsenhöhe angegeben.

```yaml
x_lines:
- x: 5.0
  label: Inlet opens
  visible: true
  show_label: true
  color: '#175CD3'
  line_style: '--'
  line_width: 1.0
  alpha: 0.9
  label_y: 0.95
  label_rotation: 90.0
  label_font_size: 9.0
  label_bg_color: '#ffffff'
  label_border_color: none
  label_bg_alpha: 0.8
  label_ha: left
  label_va: top
```

| Feld | Standard | Bedeutung |
|---|---:|---|
| `x` | `0` | X-Position in den dargestellten X-Einheiten. |
| `label` | leer | Beschriftung. |
| `visible` | `true` | Linie ein-/ausblenden. |
| `show_label` | `true` | Text ein-/ausblenden. |
| `color` | `#667085` | Linien- und Textfarbe. |
| `line_style` | `--` | Linienstil. |
| `line_width` | `1.0` | Linienbreite. |
| `alpha` | `0.9` | Linientransparenz von 0 bis 1. |
| `label_y` | `0.99` | Relative vertikale Textposition von 0 bis 1. |
| `label_rotation` | `90` | Textrotation in Grad. |
| `label_font_size` | `8` | Textgröße. |
| `label_bg_color` | `#ffffff` | Hintergrundfarbe. |
| `label_border_color` | `none` | Rahmenfarbe. |
| `label_bg_alpha` | abgeleitet | Transparenz des Texthintergrunds. |
| `label_ha` | `left` | Horizontale Ausrichtung: `left`, `center`, `right`. |
| `label_va` | `top` | Vertikale Ausrichtung: `bottom`, `center`, `top`. |

Beispiel ohne Beschriftung:

```yaml
x_lines:
- x: 0.0
  color: '#D92D20'
  line_style: ':'
  show_label: false
```

## Vertikale Ereignislinien (`events`)

```yaml
events:
- x: 5.0
  label: 'Inlet opens: 5.00 deg'
  event_type: custom
  visible: true
  show_label: true
  color: '#175CD3'
  line_style: '--'
  line_width: 1.1
  alpha: 0.9
  label_y: 0.90
  label_rotation: 90.0
  label_font_size: 9.0
  label_bg_color: white
  label_border_color: none
  label_bg_alpha: 0.8
  label_ha: right
  label_va: top
```

| Feld | Standard | Bedeutung |
|---|---:|---|
| `x` | `0` | X-Position. |
| `label` | leer | Beschriftung. |
| `event_type` | – | Metadatum, z. B. `custom`, `reference`, `valve`, `combustion`; beeinflusst das manuelle Rendering derzeit nicht. |
| `visible` | `true` | Linie ein-/ausblenden. |
| `show_label` | `true` | Beschriftung ein-/ausblenden. |
| `color` | `#666666` | Linien- und Textfarbe. |
| `line_style` | `:` | Linienstil. |
| `line_width` | `1.0` | Linienbreite. |
| `alpha` | `0.9` | Linientransparenz. |
| `label_y` | automatisch | Relative vertikale Position in Achsenkoordinaten. |
| `label_rotation` | `90` | Textrotation in Grad. |
| `label_font_size` | `7` | Textgröße. |
| `label_bg_color` | `white` | Hintergrundfarbe. |
| `label_border_color` | `none` | Rahmenfarbe. |
| `label_bg_alpha` | abgeleitet | Transparenz des Hintergrunds. |
| `label_ha` | `right` | Horizontale Ausrichtung. |
| `label_va` | `top` | Vertikale Ausrichtung. |

## Infobox (`text_box`)

### Gemeinsame Optionen

```yaml
text_box:
  enabled: true
  source: data
  title: Events
  x: 0.98
  y: 0.98
  ha: right
  va: top
  font_size: 8.0
  linespacing: 1.2
  facecolor: '#ffffff'
  edgecolor: '#111111'
  linewidth: 1.0
  alpha: 0.96
  metrics: []
```

| Feld | Standard | Bedeutung |
|---|---:|---|
| `enabled` | `false` | Infobox ein-/ausblenden. |
| `source` | `data` | `data` oder `readme`. |
| `title` | leer | Überschrift der Box. |
| `x`, `y` | `0.98`, `0.98` | Relative Position in Achsenkoordinaten. |
| `ha` | `right` | Horizontale Textausrichtung. |
| `va` | `top` | Vertikale Textausrichtung. |
| `font_size` | `7.2` | Schriftgröße. |
| `linespacing` | `1.2` | Zeilenabstand. |
| `facecolor` | `white` | Hintergrundfarbe. |
| `edgecolor` | `black` | Rahmenfarbe. |
| `linewidth` | `1.0` | Rahmenbreite. |
| `alpha` | `0.96` | Boxtransparenz. |

### Datenmetriken

```yaml
metrics:
- label: Maximum pressure
  signal_key: cylinder_1_p_Pa
  mode: max
  scale_factor: 1.0e-5
  offset: 0.0
  absolute: false
  unit: bar
  digits: 2
  fixed: true
  scientific: false
  separator: ': '
```

Unterstützte `mode`-Werte:

| Modus | Bedeutung |
|---|---|
| `first` | Erster endlicher Wert. |
| `last` | Letzter endlicher Wert; zugleich Standard für unbekannte Modi. |
| `min` | Minimum. |
| `max` | Maximum. |
| `mean` | Arithmetischer Mittelwert. |
| `delta` | Letzter minus erster Wert. |
| `integral` | Trapezintegral über `x_signal` oder die Subplot-X-Achse. Rückläufige X-Abschnitte werden übersprungen. |
| `first_where` | Erster Wert, an dem eine Bedingung erfüllt ist. |

Weitere Metrikfelder:

| Feld | Bedeutung |
|---|---|
| `label` | Text vor dem Wert. |
| `signal_key` | Auszuwertendes 
. |
| `x_signal` | Integrationsachse bei `mode: integral`; Standard ist die Subplot-X-Achse. |
| `absolute` | Betrag des Ergebnisses; bei `integral` werden die Y-Werte vor der Integration betragsmäßig verwendet. |
| `scale_factor`, `offset` | Nachträgliche Umrechnung des Kennwertes. |
| `unit` | Einheitentext. |
| `digits` | Anzahl Stellen für feste oder wissenschaftliche Darstellung. |
| `fixed` | Feste Nachkommastellen. |
| `scientific` | Wissenschaftliche Schreibweise. `fixed` hat Vorrang. |
| `separator` | Trenntext zwischen Label und Wert. |

### Bedingte Metrik `first_where`

```yaml
- label: Opening angle
  signal_key: theta_deg
  mode: first_where
  where_signal: exhaust_slot_1_A_geom_m2
  where_gt: 0.0
  unit: deg
  digits: 2
  fixed: true
```

Alternativ mehrere Bedingungssignale:

```yaml
where_signal_any:
- cylinder_1_combustion_active_0to1
- cylinder_1_added_energy_W
where_gt: 0.0
```

Schwellenoptionen:

- `where_gt`: strikt größer als der Wert.
- `where_gte` oder `where_ge`: größer oder gleich; hat Vorrang vor `where_gt`.

### Spezielle IMEP-Metrik

```yaml
- label: IMEP
  kind: imep
  cylinder: cylinder_1
  pressure_signal: cylinder_1_p_Pa
  volume_signal: cylinder_1_V_m3
  unit: bar
  digits: 2
  fixed: true
```

`pressure_signal` und `volume_signal` können entfallen, wenn `cylinder` gesetzt
ist. IMEP wird als geschlossenes numerisches `p dV`-Integral geteilt durch das
Hubvolumen und anschließend in bar berechnet.

### README-Infobox

```yaml
text_box:
  enabled: true
  source: readme
  readme_path: README.md
  title: Kennwerte
  metrics:
  - readme_key: peak_pressure
    label: Peak pressure
    unit: bar
    separator: ': '
```

| Feld | Alternative | Bedeutung |
|---|---|---|
| `readme_path` | `path` | Pfad zur Markdown-Tabelle. |
| `readme_key` | `key`, `signal_key` | Schlüssel in der ersten Tabellenspalte. |
| `label` | Schlüssel | Ausgabetext. |
| `unit` | README-Einheit | Überschreibt die gelesene Einheit. |
| `separator` | `: ` | Trenntext. |

Gesucht werden außerdem automatisch `README.md` im Ausgabeordner, dessen
Elternordner, im Plotordner und im aktuellen Arbeitsverzeichnis.

## Farben und Linienstile

Farben können beispielsweise so angegeben werden:

```yaml
color: '#D92D20'
color: red
```

Übliche Linienstile:

```yaml
line_style: '-'
line_style: '--'
line_style: '-.'
line_style: ':'
line_style: solid
line_style: dashed
line_style: dashdot
line_style: dotted
```

## Derzeit nicht unterstützte beziehungsweise ignorierte Felder

Folgende Einträge kommen teilweise in älteren Konfigurationen vor, haben im
aktuellen Renderer aber keine oder nur eingeschränkte Wirkung:

- `unit_preset`
- `show_title` im Subplot
- `min`/`max` statt `y_min`/`y_max`
- `axis_label_size` und `tick_label_size` innerhalb eines `y_axes`-Eintrags
- `color` der Y-Achse selbst
- `alpha` einer normalen Serie
- `marker` beziehungsweise ein auswählbarer Markertyp
- `label_position` und `label_offset_pt` bei `y_lines`
- frei konfigurierbare Figure-Größe und dpi
- feste Tick-Nachkommastellen oder wissenschaftliche Ticknotation
- invertierte Achsen und `symlog`
- Balken-, Scatter- oder Flächenplots; gerendert wird derzeit als Linienplot

## Kurzes Praxisbeispiel

```yaml
name: Cylinder pressure and angle
style_sheet: ../../plot_style_sheet.yaml
style:
  axis_label_size: 13
  tick_label_size: 10
  default_line_width: 1.2
figures:
- title: cylinder_pressure
  rows: 1
  cols: 1
  subplots:
  - title: Cylinder pressure
    x_signal: t_s
    x_title: Time [s]
    x_limit_mode: auto
    x_start_at_zero: true
    y_axes:
    - id: pressure
      title: Pressure [bar]
      limit_mode: manual
      y_min: 0
      y_max: 100
      tick_step: 10
      minor_tick_step: 2
    series:
    - signal_key: cylinder_1_p_Pa
      label: Cylinder 1
      axis_id: pressure
      color: '#D92D20'
      line_style: '-'
      line_width: 1.2
      scale_factor: 1.0e-5
```
