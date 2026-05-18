# Burned / Unburned Masse – Projektweiter Umbau

## Ziel
Projektweiter Einbau einer verbrannten / unverbrannten Massenabbildung, sodass:
- verbranntes Gas über alle Verbindungen mitgeführt wird,
- verbranntes Gas aus dem Zylinder ausgespült werden kann,
- dieses Restgas in Plena / Receiver / Bounce-Seite verbleiben und später wieder angesaugt werden kann,
- die unverbrannte Masse im Zylinder separat auswertbar ist.

## Umgesetztes Modell
Pro Volumen werden jetzt drei thermodynamische Zustände geführt:
1. `m_kg` = Gesamtmasse
2. `U_J` = innere Energie
3. `m_burned_kg` = verbrannter Massenanteil (Tracer)

Die unverbrannte Masse wird daraus abgeleitet:
- `m_unburned_kg = max(m_kg - m_burned_kg, 0)`

## Transport über Verbindungen
Für alle Masseströme (Valve, Slot, Orifice, Check-Valve) wird zusätzlich der verbrannte Anteil des Upstream-Volumens advectiv mitgeführt:
- Burned-Massenstrom = `mdot * burned_fraction_upstream`

Damit kann verbranntes Gas aus dem Zylinder in Receiver / Exhaust-Plenum gelangen und von dort später wieder in den Zylinder zurücktransportiert werden.

## Reaktionsabbildung im Zylinder
Die Verbrennung wandelt jetzt nicht nur Energie um, sondern verschiebt auch Masse vom unverbrannten in den verbrannten Anteil.

Dazu wird aus der Vibe-Funktion die momentane Burned-Fraction-Dynamik abgeleitet. Der Massenumsatz wird als Quelle auf `m_burned_kg` aufgebracht.

## Free-Piston Lambda-Latch
Die Free-Piston-Lambda-Latch-Logik verwendet jetzt nicht mehr die gesamte Zylindermasse, sondern die **unverbrannte** Zylindermasse als Referenz. Damit führt zurückgesaugtes verbranntes Gas nicht mehr zu einer Überschätzung der verfügbaren Frischmasse.

## Neue Ausgabesignale
Für jedes Volumen werden in den Exporten zusätzlich bereitgestellt:
- `<name>_m_burned_kg`
- `<name>_m_unburned_kg`
- `<name>_burned_fraction_0to1`

Für den Free-Piston-Sonderexport zusätzlich:
- `cylinder_m_burned_kg`
- `cylinder_m_unburned_kg`
- `cylinder_burned_fraction_0to1`

## Geänderte Dateien
- `src/thermo0d/core/state_layout.py`
- `src/thermo0d/compute/jacobian.py`
- `src/thermo0d/compute/analysis.py`
- `src/thermo0d/model/conventional/builder.py`
- `src/thermo0d/model/free_piston/builder.py`
- `src/thermo0d/model/free_piston/rhs.py`
- `src/thermo0d/model/free_piston/postprocessing.py`
- `src/thermo0d/model/free_piston/combustion_latch.py`
- `src/thermo0d/output/reconstruction.py`
- `src/thermo0d/output/plots.py`
- `src/thermo0d/physics/combustion.py`
- `src/thermo0d/physics/rhs.py`
- `src/thermo0d/physics/composition.py` (neu)
- `src/thermo0d/gui/signal_catalog.py`

## Smoke-Tests
Erfolgreich getestet mit:
- `Projekte/variants/free_piston_GenSet_V01.yaml`
- `Projekte/variants/free_piston_Vibe_V04.yaml`

Beobachtung im Vibe-Test:
- `cylinder_m_burned_kg` steigt deutlich an,
- `receiver_m_burned_kg` und `exhaust_plenum_m_burned_kg` werden > 0,
- damit ist der Transport verbrannter Masse durch das Netzwerk aktiv.

## Bekannte Vereinfachung
Das Modell verwendet weiterhin ein Ein-Gas-Eigenschaftsmodell (`cp`, `cv`, `R` global konstant). 
Die burned/unburned-Trennung ist daher aktuell eine **Massen-/Tracer-Abbildung** für Spülung, Restgas und Re-Ansaugung, noch kein vollständiges Mehrzonen- oder Mehrstoff-Gemischmodell mit separaten Stoffwerten.
