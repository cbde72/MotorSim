from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from thermo0d.physics.beck import BECK_COOL_FLAME_FUEL_NAMES

SOLVER_KINDS = ["euler", "rk4", "scipy_rk45", "scipy_bdf", "scipy_radau"]
SAMPLING_MODES = ["time", "crank_angle"]
PLOT_SOURCES = ["last_cycle_uniform", "export_rows"]
ANGLE_REFERENCES = ["absolute", "compression_tdc", "gas_exchange_tdc"]
PROFILE_ANGLE_DOMAINS = ["crank", "cam"]
VOLUME_TYPES = ["cylinder", "plenum", "bounce_chamber", "environment"]
CONNECTION_TYPES = ["valve", "slot", "orifice", "check_valve"]


@dataclass(frozen=True)
class FieldMeta:
    label: str
    kind: str
    default: Any | None = None
    choices: tuple[str, ...] = ()
    help_text: str = ""
    section: str = ""
    visible_if: tuple[str, Any] | None = None


FIELD_META: dict[str, FieldMeta] = {
    "test_description": FieldMeta("Testbeschreibung", "text", default="", help_text="Freitext zur Konfiguration.", section="root"),
    "postprocessing.outdir": FieldMeta("Output dir", "text", default=None, help_text="Ausgabeverzeichnis unterhalb von results/. Standard: Konfigurationsname ohne Extension, auf 15 Zeichen gekürzt.", section="root"),
    "postprocessing.auto_update_initial_conditions": FieldMeta("Auto update initial conditions", "bool", default=True, help_text="Fehlende Anfangsdrücke/-temperaturen automatisch aus idealer Gasgleichung ergänzen. Bei free_piston zusätzlich nach dem Lauf die initial_* Startwerte in der YAML auf den Zustand des letzten vollständigen Kompressionshubs am konfigurierten x0_m umschreiben; der bisherige Wert bleibt als Kommentar stehen.", section="root"),
    "preprocessing.gas_properties.cp_J_per_kgK": FieldMeta("cp [J/kgK]", "float", default=1005.0, help_text="Spezifische Wärmekapazität bei konstantem Druck.", section="root"),
    "preprocessing.gas_properties.cv_J_per_kgK": FieldMeta("cv [J/kgK]", "float", default=718.0, help_text="Spezifische Wärmekapazität bei konstantem Volumen.", section="root"),
    "preprocessing.gas_properties.R_J_per_kgK": FieldMeta("R [J/kgK]", "float", default=287.0, help_text="Spezifische Gaskonstante.", section="root"),
    "preprocessing.gas_properties.thermo_model": FieldMeta("Thermo model", "enum", default="constant", help_text="Stoffwertmodell: constant oder promo.", section="root"),
    "preprocessing.features.mass_flow": FieldMeta("Mass flow", "bool", default=True, help_text="Massenstrommodell aktivieren.", section="root"),
    "preprocessing.features.wall_heat": FieldMeta("Wall heat", "bool", default=False, help_text="Wandwärmeübergang global aktivieren.", section="root"),
    "preprocessing.features.combustion": FieldMeta("Combustion", "bool", default=False, help_text="Verbrennungsmodell global aktivieren.", section="root"),
    "preprocessing.features.evaporation": FieldMeta("Evaporation", "bool", default=False, help_text="Verdampfungsmodell global aktivieren.", section="root"),
    "preprocessing.features.pv_work": FieldMeta("pV work", "bool", default=True, help_text="p*dV-Arbeit berücksichtigen.", section="root"),
    "preprocessing.engine.cycle_type": FieldMeta("Cycle type", "choice", default="4t", choices=("2t", "4t"), help_text="Arbeitsspiel des Motors.", section="root"),
    "preprocessing.engine.speed_rpm": FieldMeta("Speed [rpm]", "float", default=3000.0, help_text="Drehzahl des Motors in 1/min.", section="root"),
    "simulation.dt_s": FieldMeta("dt [s]", "float", default=1e-5, help_text="Integrator-Zeitschritt für feste Solver.", section="root"),
    "simulation.total_cycles": FieldMeta("Total cycles", "int", default=6, help_text="Gesamtzahl simulierter Zyklen.", section="root"),
    "simulation.save_last_cycles": FieldMeta("Save last cycles", "int", default=1, help_text="Anzahl zu speichernder letzter Zyklen.", section="root"),
    "simulation.simulationtime": FieldMeta("Simulation time [s]", "float", default=None, help_text="Optionale Simulationsdauer in Sekunden. Für free_piston überschreibt sie die aus total_cycles abgeleitete Endzeit.", section="root"),
    "simulation.solver.kind": FieldMeta("Solver", "choice", default="rk4", choices=tuple(SOLVER_KINDS), help_text="Numerischer Integrator.", section="root"),
    "simulation.solver.rtol": FieldMeta("rtol", "float", default=1e-6, help_text="Relative Toleranz für SciPy-Solver.", section="root"),
    "simulation.solver.atol": FieldMeta("atol", "float", default=1e-9, help_text="Absolute Toleranz für SciPy-Solver.", section="root"),
    "postprocessing.csv_enabled": FieldMeta("CSV enabled", "bool", default=True, help_text="Haupt-CSV mit den resampleten Ergebnissen schreiben.", section="root"),
    "postprocessing.csv_path": FieldMeta("CSV path", "text", default="results/out.csv", help_text="Pfad der Haupt-Ergebnis-CSV relativ zum Projekt.", section="root", visible_if=("postprocessing.csv_enabled", True)),
    "postprocessing.csv_separator": FieldMeta("CSV separator", "text", default=";", help_text="Einzelnes Trennzeichen für die CSV-Ausgabe.", section="root"),
    "postprocessing.excel_enabled": FieldMeta("Excel enabled", "bool", default=False, help_text="Excel-Ausgabe aus denselben Exportdaten schreiben.", section="root"),
    "postprocessing.excel_path": FieldMeta("Excel path", "text", default="results/out.xlsx", help_text="Pfad der Excel-Ausgabe relativ zum Projekt.", section="root", visible_if=("postprocessing.excel_enabled", True)),
    "postprocessing.sampling.mode": FieldMeta("Sampling mode", "choice", default="crank_angle", choices=tuple(SAMPLING_MODES), help_text="Abtastung in Zeit oder Kurbelwinkel.", section="root"),
    "postprocessing.sampling.step_s": FieldMeta("step_s", "float", default=1e-4, help_text="Ausgabeschrittweite in Sekunden.", section="root", visible_if=("postprocessing.sampling.mode", "time")),
    "postprocessing.sampling.step_deg": FieldMeta("step_deg", "float", default=1.0, help_text="Ausgabeschrittweite in Grad Kurbelwinkel.", section="root", visible_if=("postprocessing.sampling.mode", "crank_angle")),
    "postprocessing.final_cycle_uniform_angle_export.enabled": FieldMeta("Final cycle export", "bool", default=False, help_text="Zusätzlichen letzten Zyklus auf festem Winkelraster exportieren.", section="root"),
    "postprocessing.final_cycle_uniform_angle_export.step_deg": FieldMeta("Final cycle step [deg]", "float", default=1.0, help_text="Raster für den zusätzlichen letzten Zyklus.", section="root"),
    "postprocessing.free_piston_last_ut_ot_ut_export.enabled": FieldMeta("FP UT-OT-UT export", "bool", default=False, help_text="Nur für free_piston: letzten vollständigen UT→OT→UT-Zyklus separat als CSV exportieren.", section="root"),
    "postprocessing.free_piston_last_ut_ot_ut_export.step_deg": FieldMeta("FP UT-OT-UT step [deg]", "float", default=1.0, help_text="Schrittweite der normierten Vollachse für den separaten letzten UT→OT→UT-Zyklus des Freikolbens.", section="root"),
    "postprocessing.free_piston_last_ut_ot_ut_export.axis_min_deg": FieldMeta("FP UT-OT-UT axis min [deg]", "float", default=0.0, help_text="Start der frei definierbaren Vollachse für den separaten letzten UT→OT→UT-Zyklus, z. B. -9.", section="root"),
    "postprocessing.free_piston_last_ut_ot_ut_export.axis_max_deg": FieldMeta("FP UT-OT-UT axis max [deg]", "float", default=360.0, help_text="Ende der frei definierbaren Vollachse für den separaten letzten UT→OT→UT-Zyklus, z. B. +9.", section="root"),
    "postprocessing.check_report.enabled": FieldMeta("Check report", "bool", default=True, help_text="Automatischen Ergebnis-Checkreport für den letzten Zyklus erzeugen.", section="root"),
    "postprocessing.check_report.html_enabled": FieldMeta("Check report HTML", "bool", default=False, help_text="Zusätzlich eine HTML-Zusammenfassung des Checkreports schreiben.", section="root"),
    "postprocessing.plots.enabled": FieldMeta("Plots enabled", "bool", default=True, help_text="Globale Plot-Ausgabe aktivieren.", section="root"),
    "postprocessing.plots.source": FieldMeta("Plot source", "choice", default="last_cycle_uniform", choices=tuple(PLOT_SOURCES), help_text="Datenquelle für Standardplots und Plot-Layouts.", section="root", visible_if=("postprocessing.plots.enabled", True)),
    "postprocessing.plots.output_dir": FieldMeta("Plots output dir", "text", default=None, help_text="Optionaler Zielordner für gerenderte Plot-Layouts.", section="root", visible_if=("postprocessing.plots.enabled", True)),
    "postprocessing.plots.layouts.auto_create_defaults": FieldMeta("Auto create plot defaults", "bool", default=True, help_text="Wenn keine Layout-Einträge angegeben sind, Default-Layouts plot.yaml und plot10.yaml erzeugen.", section="root", visible_if=("postprocessing.plots.enabled", True)),
    "postprocessing.plots.layouts.entries": FieldMeta("Plot layout entries", "yaml", default=[], help_text="YAML-Liste für externe Plot-Layouts. Beispiel: - enabled: true\n  path: plot.yaml\n  prefix: ''", section="root", visible_if=("postprocessing.plots.enabled", True)),
    "postprocessing.console.run_summary.enabled": FieldMeta("Console run summary", "bool", default=True, help_text="Run-Zusammenfassung in der Konsole ausgeben.", section="root"),
    "postprocessing.console.cycle_summary.enabled": FieldMeta("Console cycle summary", "bool", default=True, help_text="Zykluszusammenfassung in der Konsole ausgeben.", section="root"),
    "postprocessing.console.check_report.enabled": FieldMeta("Console check report", "bool", default=True, help_text="Checkreport-Zusammenfassung in der Konsole ausgeben.", section="root"),
    "postprocessing.console.geometry.enabled": FieldMeta("Console geometry", "bool", default=True, help_text="Geometrie- und Topologieinfos in der Konsole ausgeben.", section="root"),

    "name": FieldMeta("Name", "text", default="", help_text="Eindeutiger Modellname.", section="common"),
    "initial_pressure_Pa": FieldMeta("Initial pressure [Pa]", "float", default=101325.0, help_text="Bevorzugte Startbedingung: absoluter Anfangsdruck.", section="volume"),
    "initial_mass_kg": FieldMeta("Initial mass [kg]", "float", default=None, help_text="Legacy-Fallback, wenn kein Anfangsdruck vorliegt.", section="volume"),
    "initial_temperature_K": FieldMeta("Initial T [K]", "float", default=300.0, help_text="Anfangstemperatur des Volumens.", section="volume"),
    "initial_burned_fraction_0to1": FieldMeta("Initial burned fraction [-]", "float", default=0.0, help_text="Anteil verbrannter Masse im Volumen zu Simulationsbeginn bzw. beim Auto-Update am letzten Kompressions-Crossing bei x0_m.", section="volume"),
    "initial_burned_mass_percent": FieldMeta("Initial burned mass [%]", "float", default=None, help_text="Alternative Prozentangabe für den verbrannten Massenanteil. Hat Vorrang vor initial_burned_fraction_0to1.", section="volume"),
    "fixed_volume_m3": FieldMeta("Volume [m³]", "float", default=2e-4, help_text="Festes Volumen eines Plenums.", section="plenum"),
    "model": FieldMeta("Model", "choice", default="gas_spring", choices=("gas_spring", "gas_exchange"), help_text="Bounce-Chamber-Modell.", section="volume"),
    "chamber_diameter_m": FieldMeta("Bounce chamber diameter [m]", "float", default=0.0745, help_text="Innendurchmesser des Bounce-Raums.", section="volume"),
    "chamber_length_m": FieldMeta("Bounce chamber length [m]", "float", default=0.08, help_text="Wirksame Bounce-Hublänge.", section="volume"),
    "compression_ratio": FieldMeta("Bounce compression ratio", "float", default=2.5, help_text="Verdichtungsverhältnis des Bounce-Raums.", section="volume"),
    "chamber_volume0_m3": FieldMeta("Legacy chamber V0 [m³]", "float", default=None, help_text="Legacy-Vorgabe des Bounce-Kammervolumens.", section="volume"),
    "p0_Pa": FieldMeta("p0 [Pa]", "float", default=None, help_text="Optionaler Referenzdruck des Bounce-Polytropenmodells.", section="volume"),
    "polytropic_exponent": FieldMeta("Polytropic exponent", "float", default=1.3, help_text="Polytropenexponent des Bounce-Raums.", section="volume"),
    "pressure_Pa": FieldMeta("Pressure [Pa]", "float", default=101325.0, help_text="Fester Umgebungsdruck der Randbedingung.", section="environment"),
    "temperature_K": FieldMeta("Temperature [K]", "float", default=300.0, help_text="Feste Umgebungstemperatur der Randbedingung.", section="environment"),
    "kinematics.bore_m": FieldMeta("Bore [m]", "float", default=0.08, help_text="Zylinderbohrung.", section="cylinder"),
    "kinematics.stroke_m": FieldMeta("Stroke [m]", "float", default=0.08, help_text="Hub.", section="cylinder"),
    "kinematics.conrod_m": FieldMeta("Conrod [m]", "float", default=0.13, help_text="Pleuellänge.", section="cylinder"),
    "kinematics.compression_ratio": FieldMeta("Compression ratio", "float", default=10.0, help_text="Geometrisches Verdichtungsverhältnis.", section="cylinder"),
    "kinematics.phase_deg": FieldMeta("Phase [deg]", "float", default=0.0, help_text="Phasenversatz des Zylinders.", section="cylinder"),

    "free_piston.mechanics.piston_diameter_m": FieldMeta("Piston diameter [m]", "float", default=0.0745, help_text="Kolbendurchmesser des Freikolbens. Daraus wird intern die wirksame Kolbenfläche berechnet.", section="free_piston"),
    "free_piston.mechanics.compression_ratio": FieldMeta("Compression ratio", "float", default=10.0, help_text="Geometrisches Verdichtungsverhältnis des Freikolbenzylinders. Daraus wird intern das Restvolumen berechnet.", section="free_piston"),
    "free_piston.mechanics.kinematics_type": FieldMeta("FP kinematics type", "enum", default="linear", help_text="Mechanikmodus des Freikolbens: linear oder oscillating_rotary. Linear bleibt der kompatible Standard.", section="free_piston"),
    "free_piston.mechanics.x_min_m": FieldMeta("x_min [m]", "float", default=0.0, help_text="Obere Totpunktlage / minimale Kolbenposition des Freikolbens.", section="free_piston"),
    "free_piston.mechanics.x_max_m": FieldMeta("x_max [m]", "float", default=0.08, help_text="Untere Totpunktlage / maximale Kolbenposition des Freikolbens.", section="free_piston"),
    "free_piston.mechanics.angle_min_deg": FieldMeta("Angle min [deg]", "float", default=-9.0, help_text="Nur fuer oscillating_rotary: minimale Winkellage.", section="free_piston"),
    "free_piston.mechanics.angle_max_deg": FieldMeta("Angle max [deg]", "float", default=9.0, help_text="Nur fuer oscillating_rotary: maximale Winkellage.", section="free_piston"),
    "free_piston.mechanics.effective_radius_m": FieldMeta("Effective radius [m]", "float", default=0.05, help_text="Nur fuer oscillating_rotary: Wirkradius zur Umrechnung phi/omega in aequivalenten Hub und Geschwindigkeit.", section="free_piston"),
    "free_piston.mechanics.rotary_inertia_kg_m2": FieldMeta("Rotary inertia [kg m2]", "float", default=0.01, help_text="Nur fuer oscillating_rotary: Massentraegheitsmoment des schwingenden Rotors.", section="free_piston"),
    "free_piston.bounce.chamber_diameter_m": FieldMeta("Bounce chamber diameter [m]", "float", default=0.0745, help_text="Innendurchmesser des Bounce-Raums. Zusammen mit chamber_length_m ergibt sich das Bounce-Hubvolumen.", section="free_piston"),
    "free_piston.bounce.chamber_length_m": FieldMeta("Bounce chamber length [m]", "float", default=0.08, help_text="Wirksame Bounce-Hublänge. Zusammen mit chamber_diameter_m ergibt sich das Bounce-Hubvolumen.", section="free_piston"),
    "free_piston.bounce.compression_ratio": FieldMeta("Bounce compression ratio", "float", default=2.5, help_text="Verdichtungsverhältnis des Bounce-Raums. Daraus werden Vmin bei UT und Vmax bei OT aus dem Bounce-Hubvolumen abgeleitet.", section="free_piston"),

    "wall_heat.model": FieldMeta("Wall heat model", "choice", default="none", choices=("none", "woschni"), help_text="Wandwärme-Modell für dieses Volumen.", section="submodel"),
    "wall_heat.variant": FieldMeta("Variant", "choice", default="legacy", choices=("legacy", "promo", "classic", "swirl", "gt", "huber"), help_text="Woschni-Variante bzw. Legacy-/Quellenmodell.", section="submodel", visible_if=("wall_heat.model", "woschni")),
    "wall_heat.wall_temperature_K": FieldMeta("Wall T [K]", "float", default=450.0, help_text="Wandtemperatur für den Wärmeübergang.", section="submodel", visible_if=("wall_heat.model", "woschni")),
    "wall_heat.wall_area_m2": FieldMeta("Wall area [m²]", "float", default=0.02, help_text="Effektive benetzte Wandfläche.", section="submodel", visible_if=("wall_heat.model", "woschni")),
    "wall_heat.multiplier": FieldMeta("Multiplier", "float", default=1.0, help_text="Globaler Kalibrierfaktor für den Wärmeübergang.", section="submodel", visible_if=("wall_heat.model", "woschni")),
    "wall_heat.dp_mode": FieldMeta("Δp mode", "choice", default="off", choices=("off", "instant", "motored"), help_text="Druckdifferenzterm der Woschni-Geschwindigkeit.", section="submodel", visible_if=("wall_heat.model", "woschni")),
    "wall_heat.reference_state_mode": FieldMeta("Reference state", "choice", default="none", choices=("none", "pre_combustion_latch", "cycle_start_latch"), help_text="Referenzzustand für Varianten mit Referenzgrößen bzw. Δp-Logik.", section="submodel", visible_if=("wall_heat.model", "woschni")),
    "wall_heat.phase_mode": FieldMeta("Phase mode", "choice", default="legacy", choices=("legacy", "promo", "classic", "gt"), help_text="Phasenabhängige Umschaltung der Geschwindigkeitskoeffizienten.", section="submodel", visible_if=("wall_heat.model", "woschni")),
    "wall_heat.c1": FieldMeta("c1", "float", default=2.28, help_text="Legacy-Woschni-Konstante c1.", section="submodel", visible_if=("wall_heat.variant", "legacy")),
    "wall_heat.c2": FieldMeta("c2", "float", default=0.00324, help_text="Legacy-Woschni-Konstante c2.", section="submodel", visible_if=("wall_heat.variant", "legacy")),
    "wall_heat.c3": FieldMeta("c3", "float", default=0.0, help_text="Legacy-Woschni-Konstante c3.", section="submodel", visible_if=("wall_heat.variant", "legacy")),
    "wall_heat.cucm": FieldMeta("CUCM", "float", default=0.0, help_text="Quellen-/Promo-Drallterm CUCM.", section="submodel", visible_if=("wall_heat.model", "woschni")),
    "wall_heat.swirl_number": FieldMeta("Swirl number", "float", default=0.0, help_text="Swirl-Zahl für swirl-/GT-nahe Varianten.", section="submodel", visible_if=("wall_heat.model", "woschni")),
    "wall_heat.imep_bar": FieldMeta("IMEP [bar]", "float", default=0.0, help_text="IMEP-Eingang für Huber-nahe Varianten.", section="submodel", visible_if=("wall_heat.model", "woschni")),

    "combustion.model": FieldMeta("Combustion model", "choice", default="none", choices=("none", "vibe", "hcci_diesel"), help_text="Verbrennungsmodell dieses Volumens.", section="submodel"),
    "combustion.start_mode": FieldMeta("Start mode", "choice", default="angle", choices=("angle", "compression_hub", "hign_position"), help_text="Startfenster entweder über Winkel oder über den Free-Piston-Kompressionshub angeben.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.start_deg": FieldMeta("Start [deg]", "float", default=350.0, help_text="Startwinkel des Verbrennungsmodells.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.start_hub_m": FieldMeta("Start hub [m]", "float", default=None, help_text="Startpunkt entlang des Free-Piston-Kompressionshubs, gemessen ab BDC in Richtung TDC.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.hign_m": FieldMeta("Hign [m]", "float", default=None, help_text="Feste Zündposition relativ zum Zylinderkopf/TDC. SOC startet beim Erreichen dieser Distanz zur TDC.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.hign_mm": FieldMeta("Hign [mm]", "float", default=None, help_text="Feste Zündposition relativ zum Zylinderkopf/TDC in Millimetern. Alternative zu hign_m.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.duration_mode": FieldMeta("Duration mode", "choice", default="angle", choices=("angle", "compression_hub", "time"), help_text="Dauer des Brennverlaufs entweder über Winkel, Hub oder Zeit angeben.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.duration_deg": FieldMeta("Duration [deg]", "float", default=40.0, help_text="Dauer des Brennverlaufs in Grad.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.duration_hub_m": FieldMeta("Hub duration [m]", "float", default=None, help_text="Fensterlänge entlang des Free-Piston-Kompressionshubs, gemessen ab dem Startpunkt in Richtung TDC.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.duration_s": FieldMeta("Duration [s]", "float", default=None, help_text="Zeitbasierte Brenndauer in Sekunden.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.duration_ms": FieldMeta("Duration [ms]", "float", default=None, help_text="Zeitbasierte Brenndauer in Millisekunden. Alternative zu duration_s.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.a": FieldMeta("Vibe a", "float", default=6.9, help_text="Vibe-Formparameter a.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.m": FieldMeta("Vibe m", "float", default=2.0, help_text="Vibe-Formparameter m.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.fuel_mass_per_cycle_kg": FieldMeta("Fuel per cycle [kg]", "float", default=None, help_text="Optional: Kraftstoffmasse pro Arbeitsspiel. Alternative zu added_energy_per_cycle_J.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.lhv_J_per_kg": FieldMeta("LHV [J/kg]", "float", default=None, help_text="Optional: Unterer Heizwert. Nur zusammen mit fuel_mass_per_cycle_kg.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.added_energy_per_cycle_J": FieldMeta("Added energy [J/cycle]", "float", default=None, help_text="Direkt vorgegebene zugeführte Energie pro Arbeitsspiel.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.energy_coupling": FieldMeta("Energy coupling", "choice", default="none", choices=("none", "stroke_ratio"), help_text="Optionale Kopplung der zugeführten Energie an den Hub.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.stroke_reference_m": FieldMeta("Stroke ref [m]", "float", default=None, help_text="Referenzhub für energy_coupling = stroke_ratio.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.stroke_exponent": FieldMeta("Stroke exponent", "float", default=1.0, help_text="Exponent der Hub-Skalierung für die Energiezufuhr.", section="submodel", visible_if=("combustion.model", "vibe")),
    "combustion.angle_reference": FieldMeta("Angle ref", "choice", default="absolute", choices=tuple(ANGLE_REFERENCES), help_text="Bezugssystem der Verbrennungswinkel.", section="submodel", visible_if=("combustion.model", "vibe")),

    "combustion.ignition_model": FieldMeta("Ignition model", "choice", default="livengood_wu", choices=("livengood_wu", "beck_2003_1_arrhenius", "beck_2003_two_stage"), help_text="HCCI-Zuendverzugsmodell: generisches Livengood-Wu oder Beck 2003 mit optionaler Cool-/Hot-Flame-Stufung.", section="submodel", visible_if=("combustion.model", "hcci_diesel")),
    "combustion.burn_model": FieldMeta("Burn model", "choice", default="wiebe_autoignition", choices=("wiebe_autoignition", "vibe-beck"), help_text="Brennverlaufsmodell nach Autoignition.", section="submodel", visible_if=("combustion.model", "hcci_diesel")),
    "combustion.beck_c1_s": FieldMeta("Beck c1 [s]", "float", default=1.0e-5, help_text="Beck 1-Arrhenius Vorfaktor c1 der Zuendverzugszeit.", section="submodel", visible_if=("combustion.ignition_model", "beck_2003_1_arrhenius")),
    "combustion.beck_c2": FieldMeta("Beck c2", "float", default=-1.2, help_text="Beck Druckexponent c2 in (p/p0)^c2.", section="submodel", visible_if=("combustion.ignition_model", "beck_2003_1_arrhenius")),
    "combustion.beck_reference_pressure_bar": FieldMeta("Beck p0 [bar]", "float", default=1.0, help_text="Beck Referenzdruck p0 fuer den Druckterm.", section="submodel", visible_if=("combustion.ignition_model", "beck_2003_1_arrhenius")),
    "combustion.beck_reference_o2_percent": FieldMeta("Beck O2 air [%]", "float", default=20.94, help_text="Sauerstoffkonzentration trockener Luft fuer den linearen O2-Term nach Beck.", section="submodel", visible_if=("combustion.ignition_model", "beck_2003_1_arrhenius")),
    "combustion.beck_cf_fuel_name": FieldMeta("Beck CF fuel", "choice", default="Diesel 2", choices=BECK_COOL_FLAME_FUEL_NAMES, help_text="Kraftstoffname nach Beck Tabelle 6.2 fuer die Cool-Flame-Parametersaetze.", section="submodel", visible_if=("combustion.ignition_model", "beck_2003_two_stage")),
    "combustion.tau_activation_energy_J_per_kg": FieldMeta("Activation energy [J/kg]", "float", default=None, help_text="Optionale Beck-Aktivierungsenergie je Masse. Wenn nicht gesetzt, wird tau_activation_temperature_K genutzt.", section="submodel", visible_if=("combustion.model", "hcci_diesel")),
    "combustion.cool_flame_enabled": FieldMeta("Cool flame", "bool", default=False, help_text="Aktiviert separate Cool-Flame-Stufe vor der Hot-Flame-Hauptverbrennung.", section="submodel", visible_if=("combustion.model", "hcci_diesel")),
    "combustion.cool_flame_energy_fraction": FieldMeta("CF energy fraction", "float", default=0.08, help_text="Anteil der Zyklusenergie, der in der Cool-Flame-Stufe freigesetzt wird.", section="submodel", visible_if=("combustion.cool_flame_enabled", True)),
    "combustion.cool_flame_duration_ms": FieldMeta("CF duration [ms]", "float", default=0.3409, help_text="Zeitdauer des Cool-Flame-Vibe-Ersatzbrennverlaufs.", section="submodel", visible_if=("combustion.cool_flame_enabled", True)),

    "evaporation.model": FieldMeta("Evaporation model", "choice", default="none", choices=("none", "simple"), help_text="Verdampfungsmodell dieses Volumens.", section="submodel"),
    "evaporation.start_deg": FieldMeta("Start [deg]", "float", default=300.0, help_text="Startwinkel der Verdampfung.", section="submodel", visible_if=("evaporation.model", "simple")),
    "evaporation.duration_deg": FieldMeta("Duration [deg]", "float", default=50.0, help_text="Dauer der Verdampfung.", section="submodel", visible_if=("evaporation.model", "simple")),
    "evaporation.evaporated_mass_per_cycle_kg": FieldMeta("Evap mass/cycle [kg]", "float", default=1e-5, help_text="Verdampfte Masse pro Arbeitsspiel.", section="submodel", visible_if=("evaporation.model", "simple")),
    "evaporation.latent_heat_J_per_kg": FieldMeta("Latent heat [J/kg]", "float", default=3e5, help_text="Latente Verdampfungsenthalpie.", section="submodel", visible_if=("evaporation.model", "simple")),
    "evaporation.angle_reference": FieldMeta("Angle ref", "choice", default="absolute", choices=tuple(ANGLE_REFERENCES), help_text="Bezugssystem der Verdampfungswinkel.", section="submodel", visible_if=("evaporation.model", "simple")),

    "from_volume": FieldMeta("From", "choice", help_text="Quelle der Verbindung.", section="connection"),
    "to_volume": FieldMeta("To", "choice", help_text="Ziel der Verbindung.", section="connection"),
    "opening_angle_deg": FieldMeta("Opening angle [deg]", "float", default=110.0, help_text="Öffnungswinkel der Verbindung.", section="connection"),
    "opening_reference": FieldMeta("Opening ref", "choice", default="gas_exchange_tdc", choices=tuple(ANGLE_REFERENCES), help_text="Bezugswinkel der Öffnung.", section="connection"),
    "profile_angle_domain": FieldMeta("Profile domain", "choice", default="crank", choices=tuple(PROFILE_ANGLE_DOMAINS), help_text="Winkelbasis der Liftdatei.", section="connection"),
    "lift_scale": FieldMeta("Lift scale", "float", default=1.0, help_text="Skalierungsfaktor der Ventilhubdatei.", section="connection"),
    "lash_m": FieldMeta("Lash [m]", "float", default=0.0, help_text="Ventilspiel.", section="connection"),
    "lift_file": FieldMeta("Lift file", "text", default="data/lift_example.tsv", help_text="Datei mit Ventilhub über Winkel.", section="connection"),
    "alpha_k_file": FieldMeta("alphaK file", "text", default="data/alpha_k_example.tsv", help_text="Datei mit alphaK-Verlauf.", section="connection"),
    "source_of_data": FieldMeta("Source", "choice", default="rectangle", choices=("rectangle",), help_text="Geometriequelle des Slots.", section="connection"),
    "opening_mode": FieldMeta("Opening mode", "choice", default="by_angle", choices=("by_distance", "by_angle"), help_text="Öffnungsdefinition für den Slot.", section="connection"),
    "distance_from_tdc_m": FieldMeta("Distance from TDC [m]", "float", default=None, help_text="Abstand der Schlitzöffnung zum TDC in m. Alternative: distance_from_tdc_mm.", section="connection", visible_if=("opening_mode", "by_distance")),
    "distance_from_tdc_mm": FieldMeta("Distance from TDC [mm]", "float", default=0.0, help_text="Abstand der Schlitzöffnung zum TDC in mm. Alternative zu distance_from_tdc_m.", section="connection", visible_if=("opening_mode", "by_distance")),
    "piston_height_if_crankcase_m": FieldMeta("Piston height [m]", "float", default=0.0, help_text="Kolbenhöhe für Kurbelgehäusebezug.", section="connection"),
    "entrance_angle_deg": FieldMeta("Entrance angle [deg]", "float", default=0.0, help_text="Eintrittswinkel des Slots.", section="connection"),
    "width_m": FieldMeta("Width [m]", "float", default=None, help_text="Breite des Schlitzes in m. Alternative: width_mm.", section="connection"),
    "width_mm": FieldMeta("Width [mm]", "float", default=10.0, help_text="Breite des Schlitzes in mm. Alternative zu width_m.", section="connection"),
    "height_m": FieldMeta("Height [m]", "float", default=None, help_text="Höhe des Schlitzes in m. Alternative: height_mm.", section="connection"),
    "height_mm": FieldMeta("Height [mm]", "float", default=10.0, help_text="Höhe des Schlitzes in mm. Alternative zu height_m.", section="connection"),
    "open_fillet_radius_m": FieldMeta("Open fillet [m]", "float", default=0.0, help_text="Fillet-Radius beim Öffnen.", section="connection"),
    "full_fillet_radius_m": FieldMeta("Full fillet [m]", "float", default=0.0, help_text="Fillet-Radius bei Vollöffnung.", section="connection"),
    "number_of_identical_holes": FieldMeta("Hole count", "int", default=1, help_text="Anzahl identischer Schlitze/Löcher.", section="connection"),
    "discharge_coefficients.mode": FieldMeta("Cd mode", "choice", default="constant", choices=("constant", "table"), help_text="Quelle der Durchflussbeiwerte.", section="connection"),
    "discharge_coefficients.forward_cd": FieldMeta("Forward Cd", "float", default=0.7, help_text="Durchflussbeiwert in Strömungsrichtung.", section="connection", visible_if=("discharge_coefficients.mode", "constant")),
    "discharge_coefficients.reverse_cd": FieldMeta("Reverse Cd", "float", default=0.7, help_text="Durchflussbeiwert entgegen der Richtung.", section="connection", visible_if=("discharge_coefficients.mode", "constant")),
    "discharge_coefficients.table_file": FieldMeta("Cd table file", "text", default="", help_text="Tabellendatei für Richtung und Hub/Winkel.", section="connection", visible_if=("discharge_coefficients.mode", "table")),
    "area_m2": FieldMeta("Area [m²]", "float", default=None, help_text="Wirksame Drossel-/Orifice-Fläche in m². Alternative: diameter_mm.", section="connection"),
    "diameter_mm": FieldMeta("Diameter [mm]", "float", default=10.0, help_text="Alternativer Durchmesser in mm für Orifice/Check-Valve statt area_m2.", section="connection"),
    "forward_cd": FieldMeta("Forward Cd", "float", default=0.7, help_text="Durchflussbeiwert von from nach to.", section="connection"),
    "reverse_cd": FieldMeta("Reverse Cd", "float", default=0.7, help_text="Durchflussbeiwert von to nach from.", section="connection"),
    "discharge_coefficient": FieldMeta("Discharge coefficient", "float", default=0.7, help_text="Durchflussbeiwert des Rückschlagventils.", section="connection"),
    "cracking_pressure_Pa": FieldMeta("Cracking pressure [Pa]", "float", default=0.0, help_text="Öffnungsdruck des Rückschlagventils.", section="connection"),
}


def meta_for(key: str) -> FieldMeta | None:
    return FIELD_META.get(key)


@dataclass(frozen=True)
class SchemaHint:
    key: str
    label: str
    required: bool = False
    default_text: str = ""
    help_text: str = ""
    choices: tuple[str, ...] = ()

    def tooltip(self) -> str:
        parts: list[str] = [self.label]
        if self.help_text:
            parts.append(self.help_text)
        if self.default_text:
            parts.append(f"Default: {self.default_text}")
        if self.choices:
            parts.append("Choices: " + ", ".join(self.choices))
        return "\n".join(parts)


def get_schema_hint(payload: dict[str, Any] | None, key: str) -> SchemaHint | None:
    meta = meta_for(key)
    if meta is None:
        return None
    default_text = "" if meta.default is None else str(meta.default)
    required = meta.default is None
    return SchemaHint(
        key=key,
        label=meta.label,
        required=required,
        default_text=default_text,
        help_text=meta.help_text,
        choices=tuple(str(v) for v in meta.choices),
    )


def build_context_summary(payload: dict[str, Any] | None) -> str:
    if not isinstance(payload, dict):
        return ""
    item_type = str(payload.get("type") or payload.get("kind") or "")
    name = str(payload.get("name") or "").strip()
    bits = []
    if name:
        bits.append(name)
    if item_type:
        bits.append(f"Typ: {item_type}")
    return " | ".join(bits)
