# Generator Velocity Assist

## Ziel

Der Free-Piston-Generator kann nun nicht nur als Last bremsen, sondern bei zu geringer Kolbengeschwindigkeit aktiv als Motor wirken. Damit kann der Generator den Kolben in Bewegungsrichtung beschleunigen, wenn die Schwingung sonst einschlafen wuerde.

## Konfiguration

Der Assist ist optional im bestehenden Lastmodell `generator_controlled`:

```yaml
free_piston:
  load:
    model: generator_controlled
    damping_Ns_per_m: 0.0
    max_damping_Ns_per_m: 3000.0
    control_zone_m: 0.006
    assist_velocity_threshold_m_per_s: 1.5
    assist_force_N: 350.0
```

Die Beispielwerte sind in `Projekte/variants/free_piston_GenSet_V10e.yaml` gesetzt.

## Wirkung

- Bei `abs(v) >= assist_velocity_threshold_m_per_s` ist der Assist inaktiv.
- Bei `0 < abs(v) < assist_velocity_threshold_m_per_s` wirkt eine zusaetzliche Kraft in Bewegungsrichtung.
- Die Assist-Kraft nimmt linear ab:

```text
F_assist = assist_force_N * (1 - abs(v) / assist_velocity_threshold_m_per_s)
```

- Bei exakt `v = 0` wird kein Assist aufgebracht, weil aus der Geschwindigkeit keine Bewegungsrichtung ableitbar ist.

## Vorzeichenlogik

`compute_load_info()` liefert `force_signed_N` als Generator-Reaktionskraft in Richtung der aktuellen Geschwindigkeit. Die RHS zieht diese Kraft ab:

```python
force_load_N = -force_load_signed_N
```

Deshalb muss aktiver Assist ein entgegengesetztes Vorzeichen zu `v` in `force_signed_N` haben. Dadurch wird in der RHS eine Kraft in Bewegungsrichtung addiert.

Beispiele:

```text
v > 0  -> force_signed_N < 0 -> RHS-Kraft > 0
v < 0  -> force_signed_N > 0 -> RHS-Kraft < 0
```

## Bremsen an den Totpunkten

Die bisherige Totpunktbremse von `generator_controlled` bleibt erhalten:

- Bei Bewegung Richtung `x_min_m` wird die Distanz `x_m - x_min_m` genutzt.
- Bei Bewegung Richtung `x_max_m` wird die Distanz `x_max_m - x_m` genutzt.
- In beiden Faellen steigt die Daempfung innerhalb `control_zone_m` bis `max_damping_Ns_per_m`.

Der Assist ueberlagert diese Bremskraft. Dadurch kann der Generator in der Mitte anschieben und in Totpunktnaehe weiterhin bremsen.

## Geaenderte Dateien

- `src/thermo0d/config/models.py`
  - neue optionale Felder:
    - `assist_velocity_threshold_m_per_s`
    - `assist_force_N`
  - Validierung fuer positive Schwelle und nichtnegative Kraft

- `src/thermo0d/core/model_bundle.py`
  - neue Felder in `FreePistonModelData`

- `src/thermo0d/model/free_piston/builder.py`
  - Uebernahme der Config-Werte in das Modell-Bundle

- `src/thermo0d/model/free_piston/forces.py`
  - neue Assist-Logik in `generator_controlled`

- `src/thermo0d/model/free_piston/rhs.py`
  - Uebergabe der Assist-Parameter an die Kraftberechnung

- `src/thermo0d/model/free_piston/postprocessing.py`
- `src/thermo0d/output/reconstruction.py`
  - gleiche Kraftberechnung fuer Auswertung und rekonstruierte Signale

- `tests/test_free_piston_load_models.py`
  - Tests fuer erlaubte Config-Felder und Assist-Vorzeichen

## Verifikation

Geplanter Test:

```powershell
$env:PYTHONPATH='src'
python -m pytest tests/test_free_piston_load_models.py
```

In der aktuellen Umgebung konnte der Test nicht ausgefuehrt werden, weil der lokale `python.exe`-Start mit `Zugriff verweigert` blockiert wurde.
