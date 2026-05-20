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

## Free-Piston-Ausgaben Arbeitszylinder 1 und 2

Fuer die opposed/free-piston Varianten werden die Arbeitszylinder-Signale
zylinderweise ausgegeben. In V11/V12 sind die Praefixe normalerweise:

- `cylinder_1_...` fuer Arbeitszylinder 1
- `cylinder_2_...` fuer Arbeitszylinder 2

Die wichtigsten Signale zum Vergleich der zugefuehrten Energie sind:

| Signal Arbeitszylinder 1 | Signal Arbeitszylinder 2 | Bedeutung |
| --- | --- | --- |
| `cylinder_1_added_energy_W` | `cylinder_2_added_energy_W` | Momentane zugefuehrte Leistung durch Verbrennung. Das ist ein Leistungswert in W, kein Zyklusintegral. |
| `cylinder_1_added_energy_cycle_J` | `cylinder_2_added_energy_cycle_J` | Ueber den Zyklus integrierte zugefuehrte Energie. Dieses Signal ist fuer den direkten Energievergleich besser geeignet. |
| `cylinder_1_indicated_power_W` | `cylinder_2_indicated_power_W` | Innere/indizierte Leistung aus kumulierter pV-Arbeit und bisheriger Zykluszeit. Am Zyklusende entspricht sie der mittleren inneren Leistung des Arbeitsspiels. |
| `cylinder_1_combustion_air_mass_latched_kg` | `cylinder_2_combustion_air_mass_latched_kg` | Beim Schlitzschluss gelatchte Luftmasse. Bei `fueling_mode: lambda_from_cylinder_mass_at_slot_close` bestimmt sie die Kraftstoffmasse. |
| `cylinder_1_combustion_fuel_mass_latched_kg` | `cylinder_2_combustion_fuel_mass_latched_kg` | Aus gelatchter Luftmasse und Ziel-Lambda berechnete Kraftstoffmasse. |
| `cylinder_1_combustion_energy_latched_J` | `cylinder_2_combustion_energy_latched_J` | Aus gelatchter Kraftstoffmasse, Heizwert und Verbrennungswirkungsgrad berechnete Energie pro Arbeitsspiel. |
| `cylinder_1_lambda` | `cylinder_2_lambda` | Lambda bezogen auf die gelatchte Luft- und Kraftstoffmasse. |
| `cylinder_1_slot_area_sum_m2` | `cylinder_2_slot_area_sum_m2` | Summe der fuer diesen Zylinder betrachteten Schlitzflaechen beim Latch-Replay. |

Die wichtigsten Werte bei Brennbeginn werden aus den bestehenden Zeitreihen
an der ersten Zeile mit aktiver Verbrennung bestimmt. Bevorzugt wird
`*_combustion_active_0to1 > 0`, alternativ der erste positive Wert von
`*_added_energy_W`.

| Auswertung Arbeitszylinder 1 | Auswertung Arbeitszylinder 2 | Quelle |
| --- | --- | --- |
| Druck bei Brennbeginn | Druck bei Brennbeginn | `cylinder_1_p_Pa` bzw. `cylinder_2_p_Pa` an der Brennbeginn-Zeile. Fuer Anzeige in bar: Wert durch `1.0e5` teilen. |
| Temperatur bei Brennbeginn | Temperatur bei Brennbeginn | `cylinder_1_T_K` bzw. `cylinder_2_T_K` an der Brennbeginn-Zeile. |
| Zeitpunkt Brennbeginn | Zeitpunkt Brennbeginn | `t_s` an der Brennbeginn-Zeile. |
| Kolbenweg bei Brennbeginn | Kolbenweg bei Brennbeginn | `cylinder_1_piston_distance_from_tdc_m` bzw. `cylinder_2_piston_distance_from_tdc_m` an der Brennbeginn-Zeile. |

Bei Slot-Close-Lambda gilt naeherungsweise:

```text
m_fuel = m_air_latched / (lambda_target * AFR_stoich)
Q_zu   = m_fuel * LHV * eta_comb
```

Die innere Leistung wird aus der pV-Arbeit berechnet:

```text
P_i,1 = cylinder_1_piston_work_cycle_J / (t_s - t_cycle_start_s)
P_i,2 = cylinder_2_piston_work_cycle_J / (t_s - t_cycle_start_s)
P_i,total = P_i,1 + P_i,2
```

Im CSV/Excel-Export stehen dafuer:

| Signal Arbeitszylinder 1 | Signal Arbeitszylinder 2 | Bedeutung |
| --- | --- | --- |
| `cylinder_1_indicated_power_W` | `cylinder_2_indicated_power_W` | Mittlere innere Leistung innerhalb des laufenden Zyklus. |
| `cylinder_1_piston_work_cycle_J` | `cylinder_2_piston_work_cycle_J` | Kumulierte pV-Arbeit des laufenden Zyklus. |

Fuer einen stabilen Vergleich sollte der Wert am Ende eines vollstaendigen
Zyklus verwendet werden.

Grosse Unterschiede in `cylinder_1_added_energy_W` und
`cylinder_2_added_energy_W` koennen daher zwei Ursachen haben:

- Unterschiedliche gelatchte Energie (`*_combustion_energy_latched_J`): dann sind
  Fuellung, Spuelung oder Schlitzschluss der beiden Arbeitszylinder verschieden.
- Aehnliche gelatchte Energie, aber unterschiedliche Peaks in `*_added_energy_W`:
  dann unterscheiden sich vor allem Brennbeginn, Brenndauer oder die zeitliche
  Verteilung der Waermefreisetzung.

Weitere bereits ausgegebene Arbeitszylinder-Signale sind fuer beide Praefixe
analog verfuegbar:

| Muster fuer Arbeitszylinder 1/2 | Bedeutung |
| --- | --- |
| `cylinder_1_m_kg`, `cylinder_2_m_kg` | Gasmasse im Arbeitszylinder. |
| `cylinder_1_U_J`, `cylinder_2_U_J` | Innere Energie. |
| `cylinder_1_m_air_kg`, `cylinder_2_m_air_kg` | Luftmasse. |
| `cylinder_1_m_fuel_liquid_kg`, `cylinder_2_m_fuel_liquid_kg` | Fluessige Kraftstoffmasse. |
| `cylinder_1_m_fuel_vapor_kg`, `cylinder_2_m_fuel_vapor_kg` | Kraftstoffdampfmasse. |
| `cylinder_1_m_fuel_total_kg`, `cylinder_2_m_fuel_total_kg` | Summe aus fluessigem Kraftstoff und Kraftstoffdampf. |
| `cylinder_1_m_burned_kg`, `cylinder_2_m_burned_kg` | Verbrannte Masse. |
| `cylinder_1_m_residual_kg`, `cylinder_2_m_residual_kg` | Restgasmasse. |
| `cylinder_1_m_unburned_kg`, `cylinder_2_m_unburned_kg` | Unverbrannte Masse. |
| `cylinder_1_burned_fraction_0to1`, `cylinder_2_burned_fraction_0to1` | Verbrannter Anteil. |
| `cylinder_1_share_air_0to1`, `cylinder_2_share_air_0to1` | Luftanteil am Inventar. |
| `cylinder_1_share_fuel_vapor_0to1`, `cylinder_2_share_fuel_vapor_0to1` | Kraftstoffdampfanteil. |
| `cylinder_1_share_fuel_liquid_0to1`, `cylinder_2_share_fuel_liquid_0to1` | Fluessigkraftstoffanteil. |
| `cylinder_1_share_fuel_total_0to1`, `cylinder_2_share_fuel_total_0to1` | Gesamtkraftstoffanteil. |
| `cylinder_1_share_burned_0to1`, `cylinder_2_share_burned_0to1` | Anteil verbrannter Masse. |
| `cylinder_1_share_residual_0to1`, `cylinder_2_share_residual_0to1` | Restgasanteil. |
| `cylinder_1_share_unburned_0to1`, `cylinder_2_share_unburned_0to1` | Anteil unverbrannter Masse. |
| `cylinder_1_p_Pa`, `cylinder_2_p_Pa` | Druck. |
| `cylinder_1_T_K`, `cylinder_2_T_K` | Temperatur. |
| `cylinder_1_V_m3`, `cylinder_2_V_m3` | Volumen. |
| `cylinder_1_dVdt_m3_per_s`, `cylinder_2_dVdt_m3_per_s` | Volumenaenderungsgeschwindigkeit. |
| `cylinder_1_theta_deg`, `cylinder_2_theta_deg` | Lokaler Zykluswinkel. |
| `cylinder_1_piston_x_m`, `cylinder_2_piston_x_m` | Lokale Kolbenposition des jeweiligen Arbeitszylinders. |
| `cylinder_1_piston_distance_from_tdc_m`, `cylinder_2_piston_distance_from_tdc_m` | Abstand vom lokalen OT. |
| `cylinder_1_piston_v_m_per_s`, `cylinder_2_piston_v_m_per_s` | Lokale Kolbengeschwindigkeit. |
| `cylinder_1_mdot_in_kg_per_s`, `cylinder_2_mdot_in_kg_per_s` | Einlaufender Massenstrom. |
| `cylinder_1_mdot_out_kg_per_s`, `cylinder_2_mdot_out_kg_per_s` | Auslaufender Massenstrom. |
| `cylinder_1_A_eff_in_m2`, `cylinder_2_A_eff_in_m2` | Effektive Einlassflaeche. |
| `cylinder_1_A_eff_out_m2`, `cylinder_2_A_eff_out_m2` | Effektive Auslassflaeche. |
| `cylinder_1_enthalpy_in_W`, `cylinder_2_enthalpy_in_W` | Enthalpiestrom hinein. |
| `cylinder_1_enthalpy_out_W`, `cylinder_2_enthalpy_out_W` | Enthalpiestrom heraus. |
| `cylinder_1_wall_heat_W`, `cylinder_2_wall_heat_W` | Wandwaermestrom. |
| `cylinder_1_heat_transfer_power_W`, `cylinder_2_heat_transfer_power_W` | Waermeuebergangsleistung. |
| `cylinder_1_htc_W_per_m2K`, `cylinder_2_htc_W_per_m2K` | Waermeuebergangskoeffizient. |
| `cylinder_1_evaporation_sink_W`, `cylinder_2_evaporation_sink_W` | Verdampfungsverlust. |
| `cylinder_1_piston_work_W`, `cylinder_2_piston_work_W` | p-dV-Leistung am Kolben. |
| `cylinder_1_wall_heat_cycle_J`, `cylinder_2_wall_heat_cycle_J` | Zyklusintegral der Wandwaerme. |
| `cylinder_1_enthalpy_in_cycle_J`, `cylinder_2_enthalpy_in_cycle_J` | Zyklusintegral der Enthalpie hinein. |
| `cylinder_1_enthalpy_out_cycle_J`, `cylinder_2_enthalpy_out_cycle_J` | Zyklusintegral der Enthalpie heraus. |
| `cylinder_1_piston_work_cycle_J`, `cylinder_2_piston_work_cycle_J` | Zyklusintegral der Kolbenarbeit. |
| `cylinder_1_indicated_power_W`, `cylinder_2_indicated_power_W` | Innere/indizierte Leistung aus pV-Arbeit pro Zykluszeit. |
| `cylinder_1_evaporation_sink_cycle_J`, `cylinder_2_evaporation_sink_cycle_J` | Zyklusintegral der Verdampfungsleistung. |
| `cylinder_1_scavenging_transfer_in_kg_per_s`, `cylinder_2_scavenging_transfer_in_kg_per_s` | Spuel-Massenstrom in den Arbeitszylinder. |
| `cylinder_1_scavenging_exhaust_out_kg_per_s`, `cylinder_2_scavenging_exhaust_out_kg_per_s` | Abgas-/Spuel-Massenstrom aus dem Arbeitszylinder. |
| `cylinder_1_scavenging_burned_correction_kg_per_s`, `cylinder_2_scavenging_burned_correction_kg_per_s` | Korrektur der verbrannten Masse durch Spuelmodell. |
| `cylinder_1_scavenging_short_circuit_fraction`, `cylinder_2_scavenging_short_circuit_fraction` | Kurzschlussanteil im Spuelmodell. |
| `cylinder_1_scavenging_efficiency_0to1`, `cylinder_2_scavenging_efficiency_0to1` | Spuelwirkungsgrad. |

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
