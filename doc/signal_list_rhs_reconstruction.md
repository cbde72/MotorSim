# Thermo0D RHS- und Rekonstruktions-Signale

Diese Liste beschreibt die Signalnamen, die aus dem RHS-Ableitungsexport und aus
`SignalReconstructionService` erzeugt werden. Die konkreten Namen entstehen aus
den Namen in der Konfiguration.

Platzhalter:

- `{vol}`: Eintrag aus `bundle.volume_names`
- `{cyl}`: Zylindervolumen, also ein `{vol}` mit Typ `cylinder`
- `{conn}`: Eintrag aus `bundle.connection_names`
- `{zone}`: `cylinder`, `head` oder `piston`

## RHS-Derivative

Der RHS-Derivative-Export schreibt:

```text
t_s
d_<state_label>_dt
```

Die `<state_label>` kommen aus `StateLayout.state_labels(...)`.

Pro Volumen:

```text
d_{vol}_m_kg_dt
d_{vol}_U_J_dt
d_{vol}_m_burned_kg_dt
d_{vol}_m_air_kg_dt
d_{vol}_m_fuel_liquid_kg_dt
```

Free-Piston, bei einem mechanischen Freiheitsgrad:

```text
d_free_piston_x_m_dt
d_free_piston_v_m_per_s_dt
```

Free-Piston, bei mehreren mechanischen Freiheitsgraden:

```text
d_free_piston_x_m_dt
d_free_piston_q<N>_x_m_dt
d_free_piston_v_m_per_s_dt
d_free_piston_q<N>_v_m_per_s_dt
```

Wandtemperatur-Zustände, falls das Wandtemperaturmodell aktiv ist:

```text
d_{vol}_wall_cylinder_temperature_K_dt
d_{vol}_wall_head_temperature_K_dt
d_{vol}_wall_piston_temperature_K_dt
```

Hinweis: Die Cycle-Average-Hilfszustände mit Namen wie
`{vol}_wall_temperature_alpha_avg_W_per_m2K` werden im aktuellen
RHS-Derivative-Export herausgefiltert.

## Globale Rekonstruktionssignale

```text
t_s
cycle_index
theta_deg
theta_local_deg
```

## Volumen-Signale

Diese Signale werden fuer jedes Volumen `{vol}` erzeugt, soweit das Volumen in
der jeweiligen Architektur sinnvoll rekonstruierbar ist.

```text
{vol}_m_kg
{vol}_U_J
{vol}_m_burned_kg
{vol}_m_air_kg
{vol}_m_fresh_gas_kg
{vol}_m_fuel_liquid_kg
{vol}_m_fuel_vapor_kg
{vol}_m_fuel_total_kg
{vol}_m_inventory_total_kg
{vol}_m_unburned_kg
{vol}_burned_fraction_0to1
{vol}_share_air_0to1
{vol}_share_fuel_vapor_0to1
{vol}_share_fuel_liquid_0to1
{vol}_share_fuel_total_0to1
{vol}_share_burned_0to1
{vol}_share_fresh_gas_0to1
{vol}_share_unburned_0to1
{vol}_T_K
{vol}_p_Pa
{vol}_cp_J_per_kgK
{vol}_cv_J_per_kgK
{vol}_R_J_per_kgK
{vol}_kappa
{vol}_thermo_lambda
{vol}_V_m3
{vol}_dVdt_m3_per_s
{vol}_theta_deg
```

Free-Piston-spezifisch fuer Zylinder und Bounce-Chamber-Volumen:

```text
{vol}_piston_x_m
{vol}_piston_distance_from_tdc_m
{vol}_piston_v_m_per_s
```

## Zylinder-Bilanz- und Quellterme

Diese Signale werden fuer Zylinder `{cyl}` erzeugt.

```text
{cyl}_mdot_in_kg_per_s
{cyl}_mdot_out_kg_per_s
{cyl}_A_eff_in_m2
{cyl}_A_eff_out_m2
{cyl}_enthalpy_in_W
{cyl}_enthalpy_out_W
{cyl}_wall_heat_W
{cyl}_heat_transfer_power_W
{cyl}_htc_W_per_m2K
{cyl}_added_energy_W
{cyl}_combustion_fraction_0to1
{cyl}_combustion_fraction_rate_1_per_s
{cyl}_combustion_soc_time_s
{cyl}_combustion_soc_energy_J
{cyl}_cool_flame_time_s
{cyl}_cool_flame_energy_J
{cyl}_cool_flame_qdot_W
{cyl}_cool_flame_qdot_peak_W
{cyl}_cool_flame_peak_delay_s
{cyl}_cool_flame_duration_s
{cyl}_hcci_ignition_delay_s
{cyl}_hcci_cool_ignition_delay_s
{cyl}_hcci_ignition_integral_0to1
{cyl}_hcci_cool_ignition_integral_0to1
{cyl}_evaporation_sink_W
{cyl}_piston_work_W
```

Wandtemperatur-Zonen, falls aktiv:

```text
{cyl}_wall_{zone}_temperature_K
{cyl}_wall_{zone}_heat_W
{cyl}_wall_{zone}_heat_transfer_power_W
{cyl}_wall_{zone}_heat_share_0to1
{cyl}_wall_temperature_K
{cyl}_wall_heat_zones_sum_W
```

Scavenging/Spuelung, falls aktiv:

```text
{cyl}_scavenging_transfer_in_kg_per_s
{cyl}_scavenging_exhaust_out_kg_per_s
{cyl}_scavenging_burned_correction_kg_per_s
{cyl}_scavenging_short_circuit_fraction
{cyl}_scavenging_efficiency_0to1
```

Gelatchte Free-Piston-Verbrennung, falls aktiv:

```text
{cyl}_combustion_air_mass_latched_kg
{cyl}_combustion_fuel_mass_latched_kg
{cyl}_combustion_energy_latched_J
{cyl}_lambda
{cyl}_slot_area_sum_m2
```

Burn-window-Signale, falls ein `added_energy_W`-Signal fuer das Volumen
vorhanden ist:

```text
{vol}_combustion_active_0to1
{vol}_burn_window_index
{vol}_released_energy_window_progress_J
{vol}_released_energy_window_J
```

## Connection-Signale

Diese Signale werden fuer jede Verbindung `{conn}` erzeugt. Nicht jeder
Verbindungstyp belegt jedes Geometriesignal.

Ventil:

```text
{conn}_valve_lift_m
{conn}_A_geom_m2
{conn}_A_eff_forward_m2
{conn}_A_eff_reverse_m2
```

Slot:

```text
{conn}_slot_height_m
{conn}_A_geom_m2
{conn}_A_eff_forward_m2
{conn}_A_eff_reverse_m2
```

Orifice:

```text
{conn}_A_geom_m2
{conn}_A_eff_forward_m2
{conn}_A_eff_reverse_m2
```

Check-Valve:

```text
{conn}_A_geom_m2
{conn}_A_eff_forward_m2
{conn}_A_eff_reverse_m2
{conn}_open_0to1
```

Massestrom und Speziesanteile:

```text
{conn}_mdot_kg_per_s
{conn}_mdot_burned_kg_per_s
{conn}_mdot_air_kg_per_s
{conn}_mdot_fuel_vapor_kg_per_s
{conn}_mdot_unburned_kg_per_s
```

## Free-Piston Global-Signale

```text
free_piston_x_m
free_piston_distance_from_tdc_m
free_piston_v_m_per_s
free_piston_q
free_piston_q_dot
free_piston_a_m_per_s2
bounce_volume_m3
bounce_pressure_Pa
free_piston_F_gas_N
free_piston_F_bounce_N
free_piston_F_friction_N
free_piston_F_load_N
free_piston_F_net_N
free_piston_generator_power_W
free_piston_generator_electrical_power_W
free_piston_generator_damping_eff_Ns_per_m
free_piston_generator_force_base_N
free_piston_generator_force_power_N
free_piston_generator_force_stop_N
free_piston_generator_distance_to_stop_m
free_piston_generator_midstroke_weight
free_piston_slot_area_sum_m2
free_piston_combustion_mass_latched_kg
free_piston_combustion_fuel_mass_latched_kg
free_piston_combustion_energy_latched_J
free_piston_combustion_lambda
```

## Legacy-Cycle-Integrale

Nach der Rekonstruktion fuegt das Legacy-Postprocessing aus vorhandenen
Leistungs- und Massenstromsignalen weitere kumulierte Signale hinzu.

Aus Leistungs-Signalen:

```text
{prefix}_wall_heat_cycle_J
{prefix}_wall_cylinder_heat_cycle_J
{prefix}_wall_head_heat_cycle_J
{prefix}_wall_piston_heat_cycle_J
{prefix}_wall_heat_zones_sum_cycle_J
{prefix}_added_energy_cycle_J
{prefix}_enthalpy_in_cycle_J
{prefix}_enthalpy_out_cycle_J
{prefix}_piston_work_cycle_J
{prefix}_evaporation_sink_cycle_J
```

Aus Massenstrom-Signalen:

```text
{prefix}_mdot_in_cycle_kg
{prefix}_mdot_out_cycle_kg
```

Aus jedem `{prefix}_U_J`:

```text
{prefix}_delta_U_cycle_J
{prefix}_enthalpy_net_cycle_J
{prefix}_energy_balance_residual_J
{prefix}_indicated_power_W
```

Wenn zusaetzlich `{prefix}_m_kg` existiert:

```text
{prefix}_delta_m_cycle_kg
{prefix}_mass_balance_residual_kg
```

## Alias-Hinweis

Die Rekonstruktion legt Kompatibilitaets-Aliase an, wenn es nur eine Instanz
eines nummerierten Prefixes gibt. Beispiel:

```text
cylinder_1_p_Pa -> cylinder_p_Pa
compressor_1_m_kg -> bounce_m_kg
transfer_slot_1_mdot_kg_per_s -> transfer_slot_mdot_kg_per_s
```

Fuer eine konkrete Simulation bleibt der CSV-Header des Legacy-Exports die
verbindliche Liste der tatsaechlich geschriebenen Signale.
