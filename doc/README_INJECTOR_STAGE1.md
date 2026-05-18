# Injector Stage 1 Patch

Dieser Patch setzt die erste Etappe für den Free-Piston-Injektorpfad um.

## Enthalten

- neuer `fueling_mode`:
  - `lambda_from_cylinder_air_at_slot_close_vapor_injector`
- neue Config-Felder in `combustion`:
  - `injection_duration_s`
  - `injection_duration_ms`
- Free-Piston-Runtime-Felder für einen Vapor-Injektor
- Slot-Close-Latch bestimmt aus der **gelatchten Luftmasse** die Ziel-Kraftstoffmasse
- Injektor speist diese Masse über die Einspritzdauer direkt in `m_fuel_vapor` bzw. den Gaszustand ein

## Wichtig

Dies ist bewusst nur **Etappe 1**:

- der Injektorpfad ist vorhanden
- die Ziel-Kraftstoffmasse wird aus `lambda_target` und gelatchter Zylinder-Luftmasse berechnet
- der Kraftstoff wird direkt als Dampfmasse in den Zylinder eingespeist

Die Verbrennung ist in diesem Patch **noch nicht vollständig auf expliziten Verbrauch von `m_fuel_vapor` und `m_air` umgebaut**. Das ist der nächste Schritt.

## Beispiel

```yaml
combustion:
  model: vibe
  fueling_mode: lambda_from_cylinder_air_at_slot_close_vapor_injector
  lambda_target: 1.0
  injection_duration_ms: 0.5
  lhv_J_per_kg: 43000000.0
  afr_stoich_kg_air_per_kg_fuel: 14.5
  combustion_efficiency_0to1: 0.98
```
