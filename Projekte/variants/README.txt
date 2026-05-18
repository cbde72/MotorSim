Free-Piston-Coldflow-Oszillationspaket

Enthalten:
- free_piston_coldflow_oscillating.yaml
- plot_fp.yaml

Wesentliche Anpassungen gegenüber der Ursprungsversion:
- Zylinder-Startdruck: 120 kPa -> 105 kPa
- Scavenge-Plenum / ambient_in: 160/180 kPa -> 130/130 kPa
- Exhaust-Plenum: 110 kPa -> 105 kPa
- Bounce-Gasfeder: p0 150 kPa -> 220 kPa
- Bounce-Referenzvolumen: 3.0e-4 -> 1.5e-4 m^3
- Reibung: fc 20 -> 5 N, cv 10 -> 2 N*s/m
- Lastdämpfung: 120 -> 20 N*s/m
- Startlage: x0 0.020 -> 0.0 m
- Simulationszeit: 0.005 -> 0.12 s

Validiert auf dem hochgeladenen Phase-C-Stand.
Beobachtet wurden 3 Geschwindigkeits-Vorzeichenwechsel bei ca. 0.029 s, 0.0622 s und 0.0952 s.
