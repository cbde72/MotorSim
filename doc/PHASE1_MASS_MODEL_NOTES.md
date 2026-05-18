# Phase 1 – sauberes Massenmodell

## Neues Zustandsmodell pro Volumen

Der thermodynamische Zustandsvektor je Volumen wurde von 3 auf 5 Zustände erweitert:

1. `m_gas_kg`
2. `U_J`
3. `m_burned_kg`
4. `m_air_kg`
5. `m_fuel_liquid_kg`

Abgeleitet wird:

- `m_fuel_vapor_kg = m_gas - m_burned - m_air`
- `m_fuel_total_kg = m_fuel_vapor + m_fuel_liquid`
- `m_unburned_kg = m_gas - m_burned`

## Umgesetzte Punkte

- `StateLayout` auf 5 Zustände pro Volumen erweitert
- Builder für konventionell und Free-Piston initialisieren jetzt `m_air` und `m_fuel_liquid`
- Massentransport in den RHS-Funktionen transportiert jetzt explizit:
  - Gesamt-Gasmasse
  - verbrannte Gasmasse
  - Luftmasse
  - flüssiger Kraftstoff bleibt lokal
  - gasförmiger Kraftstoff ergibt sich implizit aus dem Rest
- Verdampfung wirkt jetzt zusätzlich als Massenübergang:
  - `m_fuel_liquid -> m_gas`
- Verbrennung verschiebt jetzt Masse von unburned nach burned und reduziert explizit die Luftmasse anteilig
- Rekonstruktion/CSV erweitert um:
  - `*_m_air_kg`
  - `*_m_fuel_liquid_kg`
  - `*_m_fuel_vapor_kg`
  - `*_m_fuel_total_kg`
- Free-Piston Latch arbeitet jetzt mit expliziter Luftmasse statt mit `m_unburned`

## Wichtige Grenzen dieses Phase-1-Patches

- `m_fuel_vapor` ist noch **abgeleitet**, nicht eigener expliziter Zustand
- Verbrennung verteilt die Umwandlung aktuell **anteilig nach vorhandener unburned Gasmasse**; es gibt noch **keine harte stöchiometrische O2-Limitierung**
- Bei lambda-gelatchter Free-Piston-Verbrennung ist die energetische Latch-Logik weiter vorhanden; die Stoffwerte folgen aber jetzt primär dem expliziten Massenzustand
- Jacobian-Analytik für den alten 2/3-Zustandsfall bleibt im Code, für den neuen 5-Zustandsfall greift automatisch der FD-Pfad

## Smoke-Test

Erfolgreich getestet:

- Konfig geladen und Bundle gebaut für `free_piston_GenSet_V09f.yaml`
- RHS bei `t=0` erfolgreich ausgewertet
- Python-Compile-Lauf über `src/thermo0d` erfolgreich
