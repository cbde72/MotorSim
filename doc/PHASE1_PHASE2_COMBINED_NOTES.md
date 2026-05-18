# Phase 1 + Phase 2 – Massenmodell und reduzierte Mischungs-Stoffwerte

Dieses Patch kann direkt auf das hochgeladene Basisarchiv angewendet werden.

## Enthalten

### Phase 1 – sauberes Massenmodell
Pro Volumen werden nun folgende Zustände geführt:

- `m_gas`
- `U`
- `m_burned`
- `m_air`
- `m_fuel_liquid`

Abgeleitet:

- `m_fuel_vapor = m_gas - m_air - m_burned`
- `m_fuel_total = m_fuel_vapor + m_fuel_liquid`

### Phase 2 – reduzierte Mischungs-Stoffwerte
Das bisherige Promo-Stoffwertmodell wird für `R`, `cp`, `cv` und `kappa` auf ein reduziertes Dreikomponentenmodell umgestellt:

- frische Luft
- Kraftstoffdampf
- verbranntes Gas

Die Diagnosegröße `lambda` bleibt erhalten, wird aber aus `m_air` und `m_fuel_vapor` gebildet.

## Kernwirkung

- Verdampfung verschiebt Masse von `m_fuel_liquid` nach `m_gas`
- Luftmasse wird explizit transportiert
- Brennmasse bleibt explizit transportiert
- Stoffwerte werden aus den aktuellen Massenanteilen gemischt
- Export/Rekonstruktion geben die neuen Massen und gemischten Stoffwerte aus

## Validierung

Geprüft auf dem hochgeladenen Archiv:

- `python -m compileall src/thermo0d` erfolgreich
- Smoke-Test mit `Projekte/variants/free_piston_GenSet_V09f.yaml` erfolgreich
- `compute_free_piston_rhs(0.0, y_init, bundle)` liefert endliche Werte

## Noch nicht enthalten

- keine vollständigen NASA-Polynome
- keine explizite O2-limitierte stöchiometrische Verbrennung
- keine Aufspaltung verbrannter Produkte in Einzelspezies
