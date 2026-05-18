# Free-Piston Thermo Components Patch

Dieser Patch ist als **Korrektur-/Konsolidierungspatch auf Basis von Phase 1 + Phase 2** gedacht.

Er stellt den Free-Piston-Thermopfad so um, dass die Stoffwerte `p`, `T`, `R`, `cp`, `cv`, `kappa`
nicht mehr aus `m_total + lambda(total,fuel)` kommen, sondern aus der reduzierten Mischung:

- frische Luft
- Kraftstoffdampf
- verbranntes Gas

## Umgestellt in

- `src/thermo0d/model/free_piston/rhs.py`
- `src/thermo0d/model/free_piston/postprocessing.py`
- `src/thermo0d/output/reconstruction.py`
- `src/thermo0d/physics/quellen_props.py`

## Technische Wirkung

Neue Mischungseingänge für den Free-Piston-Pfad:

- `m_air`
- `m_fuel_vapor`
- `m_burned`

Neue reduzierte Stoffwertfunktionen:

- `lambda_from_air_and_fuel_mass(...)`
- `properties_from_mass_energy_components_quellen(...)`
- `pressure_from_mass_energy_components_quellen(...)`

## Erwartete Basis

Der Patch setzt den Phase-1-Zustandsraum bereits voraus:

- `m_gas`
- `U`
- `m_burned`
- `m_air`
- `m_fuel_liquid`

und damit die StateLayout-Helfer:

- `air_mass_from_state(...)`
- `fuel_vapor_mass_from_state(...)`
- `burned_mass_from_state(...)`

## Verifikation

Geprüft auf dem kombinierten Stand aus Originalarchiv + `phase1_phase2_combined_patch.zip`:

- `python -m compileall src/thermo0d` erfolgreich
- Bundle-Aufbau für `Projekte/variants/free_piston_GenSet_V09f.yaml` erfolgreich
- `compute_free_piston_rhs(0.0, y_init, bundle)` liefert endliche Werte
