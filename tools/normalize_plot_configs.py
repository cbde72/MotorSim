"""Normalize all Thermo0D plot YAMLs to the project-wide English style guide."""

from __future__ import annotations

import argparse
import re
from pathlib import Path
from typing import Any

import yaml


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIRS = (
    ROOT / "Projekte" / "variants" / "plot_cycle",
    ROOT / "Projekte" / "variants" / "plot_total",
    ROOT / "Projekte" / "variants" / "plot_v40",
    ROOT / "Projekte" / "plot_configs",
)

BLACK = "#111111"
GRAY = "#667085"
PRESSURE_C1 = "#66B3FF"
PRESSURE_C2 = "#0050A4"
TEMPERATURE_C1 = "#FF8A80"
TEMPERATURE_C2 = "#B71C1C"
INLET_BLUE = "#175CD3"
OUTLET_RED = "#D92D20"
ENERGY_RED = "#C2185B"
CYLINDER_1_LIGHT = "#7DD3C7"
CYLINDER_2_DARK = "#087A6A"

DISPLAY_KEYS = {"name", "title", "label", "x_title"}

EXACT_TRANSLATIONS = {
    "Druck": "Pressure",
    "Temperatur": "Temperature",
    "Zeit [s]": "Time [s]",
    "Kurbelwinkel [deg]": "Crank angle [deg]",
    "Kurbelwinkel [°]": "Crank angle [deg]",
    "Kolbenweg": "Piston position",
    "Kolbengeschwindigkeit": "Piston velocity",
    "Geschwindigkeit": "Velocity",
    "Beschleunigung": "Acceleration",
    "Kraft [N]": "Force [N]",
    "Kräfte über Zeit": "Forces over time",
    "Drücke über Zeit": "Pressures over time",
    "Temperaturen über Zeit": "Temperatures over time",
    "Massenströme über Zeit": "Mass flows over time",
    "Gesamtmasse über Zeit": "Total mass over time",
    "Unverbrannte Masse über Zeit": "Unburned mass over time",
    "Verbrannte Masse über Zeit": "Burned mass over time",
    "Zugeführte Energie": "Added energy",
    "Zugefuehrte Energie": "Added energy",
    "Zugeführte Energy": "Added energy",
    "Generatorleistung": "Generator power",
    "Wandwärme Verluste": "Wall heat losses",
    "Wandwärme [J]": "Wall heat [J]",
    "Waermeuebergangskoeffizient": "Heat transfer coefficient",
    "Momentane Wandwaermeleistung": "Instantaneous wall heat power",
    "Gas- und Wandtemperaturen": "Gas and wall temperatures",
    "Kompressor-Wandwaermeleistung": "Compressor wall heat power",
    "Kompressor-Waermeuebergangskoeffizient": "Compressor heat transfer coefficient",
    "Kompressor-Gas- und Wandtemperaturen": "Compressor gas and wall temperatures",
    "Kumulierte Wandwaermeenergie": "Cumulative wall heat energy",
    "Kumulierte Kompressor-Wandwaermeenergie": "Cumulative compressor wall heat energy",
    "Einlasshub": "Intake valve lift",
    "Auslasshub": "Exhaust valve lift",
    "Auslaßhub": "Exhaust valve lift",
    "Einlassstrom": "Intake mass flow",
    "Auslasstrom": "Exhaust mass flow",
    "Einströmender Massenstrom": "Inflowing mass flow",
    "Ausströmender Massenstrom": "Outflowing mass flow",
    "Öffnungsquerschnitt [mm²]": "Opening area [mm²]",
    "Eff. Fläche [mm²]": "Effective area [mm²]",
    "Volumen": "Volume",
    "Energie [J]": "Energy [J]",
    "Innere Energie": "Internal energy",
    "Leistung [W]": "Power [W]",
    "Leistung [kW]": "Power [kW]",
    "Masse [mg]": "Mass [mg]",
    "Massenstrom [kg/s]": "Mass flow [kg/s]",
    "Massenstrom [g/s]": "Mass flow [g/s]",
    "Massenstrom [mg/s]": "Mass flow [mg/s]",
    "Zylinder 1": "Cylinder 1",
    "Zylinder 2": "Cylinder 2",
    "Kompressor 1": "Compressor 1",
    "Kompressor 2": "Compressor 2",
    "Luft": "Air",
    "Verbrannt": "Burned gas",
    "Restgasanteil": "Residual-gas fraction",
    "Summe": "Total",
    "Kolben": "Piston",
    "Kopf": "Head",
    "Zylinderwand": "Cylinder liner",
    "Nettokraft": "Net force",
    "Gaskraft": "Gas force",
    "Reibkraft": "Friction force",
    "Lastkraft": "Load force",
    "Bounce-Kraft": "Bounce force",
    "Zylinderdruck": "Cylinder pressure",
    "Zylindertemperatur": "Cylinder temperature",
    "Zylindervolumen": "Cylinder volume",
    "Zylindermasse": "Cylinder mass",
    "Zugefuehrte Energie": "Added energy",
    "Waermefreisetzung und Lambda": "Heat release and lambda",
    "Cranking force und Cranking torque": "Cranking force and cranking torque",
    "Cylinder 1 Temperatureee": "Cylinder 1 temperature",
    "Cylinder 2 Temperatureee": "Cylinder 2 temperature",
    "Cylinderdruck (last stroke)": "Cylinder pressure (last stroke)",
    "Cylinderdruck [bar]": "Cylinder pressure [bar]",
    "Cylinderdruck over time": "Cylinder pressure over time",
    "Cylinderdruck vs. Crank angle": "Cylinder pressure vs. crank angle",
    "Cylindervolumen vs. Cylinderdruck": "Cylinder volume vs. cylinder pressure",
    "Forcestoffdosierung und Verbrauch": "Fuel metering and consumption",
    "Free-Piston Masses aller vorhandenen Volumes": "Free-piston masses of all volumes",
    "Free-Piston Pressureverläufe aller Volumes": "Free-piston pressure traces of all volumes",
    "Free-Piston Slots und Aeff over piston position": "Free-piston slots and effective areas over piston position",
    "Free-Piston Slots und Aeff over time": "Free-piston slots and effective areas over time",
    "Free-Piston Temperatureverläufe aller Volumes": "Free-piston temperature traces of all volumes",
    "Fresh gas und burned gas im Cylinder - last BDC-TDC-BDC cycle": "Fresh and burned gas in cylinder — last BDC-TDC-BDC cycle",
    "Fresh gas, burned gas und Residual gas im Cylinder": "Fresh gas, burned gas and residual gas in cylinder",
    "Fresh gas- und Residual gasanteil": "Fresh-gas and residual-gas fractions",
    "Generator power und added energy over time": "Generator power and added energy over time",
    "Injection und Combustion": "Injection and combustion",
    "Kolbenarbeit (cumulative)": "Piston work (cumulative)",
    "Kolbenarbeit [J]": "Piston work [J]",
    "Kolbenarbeit cumulative / Valve lift": "Cumulative piston work / valve lift",
    "Last-Cycle Zoom - Composition und Peak": "Last-cycle zoom — composition and peak",
    "Last-Cycle Zoom - Overlap und Modellantwort": "Last-cycle zoom — overlap and model response",
    "Luft, Residual gas und gelatchte Luftmasse": "Air, residual gas and latched air mass",
    "Mass im Cylinder [mg]": "Mass in cylinder [mg]",
    "Mehrparameter-Analyse: Pressure, Temperature, Volume": "Multi-parameter analysis: pressure, temperature, volume",
    "Pressure, Hub und gelatchte Luftmasse": "Pressure, stroke and latched air mass",
    "Pressurepeak und Kolbenhub": "Pressure peak and piston stroke",
    "Residual gas und Luft im Cylinder": "Residual gas and air in cylinder",
    "Residual gasabbau gegen Transfer- und Exhauststrom": "Residual-gas reduction vs. transfer and exhaust flow",
    "Scavengkorrektur im letzten Fenster": "Scavenging correction in the last window",
    "Scavengung - Composition im Cylinder": "Scavenging — composition in cylinder",
    "Scavengung - Feedback auf Verdichtung und Peak": "Scavenging — feedback on compression and peak",
    "Scavengung - Modellantwort": "Scavenging — model response",
    "Scavengung - Slot Overlap und Massesstroeme": "Scavenging — slot overlap and mass flows",
    "Slot-Overlap im letzten Fenster": "Slot overlap in the last window",
    "Temperaturee": "Temperature",
    "Temperaturee [K]": "Temperature [K]",
    "Temperatureee [K]": "Temperature [K]",
    "Total-, Luft-, Burned- und Residual gasstrom": "Total, air, burned-gas and residual-gas flow",
    "Totalinventar und Cylinderkomponenten": "Total inventory and cylinder components",
    "Transfer und Exhaust over Time": "Transfer and exhaust over time",
    "V40 Wall heatpruefung Cylinder und Compressoren": "V40 wall-heat verification — cylinders and compressors",
    "V40 Compressor-Wall heat Detailpruefung": "V40 compressor wall-heat detail verification",
    "V40_Wall heat_energy_Leistung_HTC_Temperature": "V40 wall heat — energy, power, HTC and temperature",
    "Velocity und Acceleration over time": "Velocity and acceleration over time",
    "Velocity, Acceleration und Piston position over time": "Velocity, acceleration and piston position over time",
    "Wall heat Kolben": "Piston wall heat",
    "Hub [mm] / Luftmasse [mg]": "Stroke [mm] / air mass [mg]",
    "pV-Diagramm: Letzter vollständiger Hub (UT-OT-UT)": "pV diagram: last complete stroke (BDC-TDC-BDC)",
    "ΔU seit Zyklusstart": "ΔU since cycle start",
}

REPLACEMENTS = (
    ("letzter UT-OT-UT-Zyklus", "last BDC-TDC-BDC cycle"),
    ("letztes Arbeitsspiel", "last working cycle"),
    ("letzter vollständiger Hub", "last complete stroke"),
    ("letzter Hub", "last stroke"),
    ("Generatorleistung", "Generator power"),
    ("Betragsintegral", "absolute integral"),
    ("Qdot Wand", "Wall heat rate"),
    ("Kolbenhub", "piston stroke"),
    ("Druckpeak", "pressure peak"),
    ("Zyklusstart", "cycle start"),
    ("Modellantwort", "model response"),
    ("pruefung", "verification"),
    ("Pruefung", "Verification"),
    ("Leistung", "Power"),
    ("Wand", "Wall"),
    ("Luft", "Air"),
    ("gelatchte", "latched"),
    ("Hub", "stroke"),
    ("aller", "of all"),
    ("vorhandenen", "available"),
    ("seit", "since"),
    ("gegen", "versus"),
    ("auf", "on"),
    ("im", "in"),
    ("und", "and"),
    ("zugeführte", "added"),
    ("zugefuehrte", "added"),
    ("über Kurbelwinkel", "over crank angle"),
    ("über Kolbenweg", "over piston position"),
    ("über Zeit", "over time"),
    ("kumuliert", "cumulative"),
    ("Kumulierte", "Cumulative"),
    ("Wandwärme", "Wall heat"),
    ("Wandwaerme", "Wall heat"),
    ("Waerme", "Heat"),
    ("Wärme", "Heat"),
    ("Zugeführte", "Added"),
    ("Zugefuehrte", "Added"),
    ("Energie", "energy"),
    ("Druck", "Pressure"),
    ("Drücke", "Pressures"),
    ("Temperatur", "Temperature"),
    ("Temperaturen", "Temperatures"),
    ("Volumen", "Volume"),
    ("Massenströme", "Mass flows"),
    ("Massenstrom", "Mass flow"),
    ("Massen", "Masses"),
    ("Masse", "Mass"),
    ("Einlass", "Intake"),
    ("Auslass", "Exhaust"),
    ("Öffnungsquerschnitt", "Opening area"),
    ("Oeffnungsquerschnitt", "Opening area"),
    ("Öffnungen", "Openings"),
    ("Ventilhub", "Valve lift"),
    ("Slot-Höhe", "Slot height"),
    ("Slot-Höhen", "Slot heights"),
    ("Kolbenweg", "Piston position"),
    ("Kolbengeschwindigkeit", "Piston velocity"),
    ("Geschwindigkeit", "Velocity"),
    ("Beschleunigung", "Acceleration"),
    ("Kräfte", "Forces"),
    ("Kraft", "Force"),
    ("Zylinder", "Cylinder"),
    ("Kompressor", "Compressor"),
    ("Frischgas", "Fresh gas"),
    ("Restgas", "Residual gas"),
    ("Verbranntes Gas", "Burned gas"),
    ("verbranntes Gas", "burned gas"),
    ("Verbrannte", "Burned"),
    ("Unverbrannte", "Unburned"),
    ("Kraftstoff", "Fuel"),
    ("flüssig", "liquid"),
    ("fluessig", "liquid"),
    ("gasförmig", "vapor"),
    ("gasfoermig", "vapor"),
    ("Gesamt", "Total"),
    ("gesamt", "total"),
    ("Anteil", "Fraction"),
    ("Spuel", "Scaveng"),
    ("Spül", "Scaveng"),
    ("Zuend", "Ignition"),
    ("Zünd", "Ignition"),
    ("Einspritzung", "Injection"),
    ("Verbrennung", "Combustion"),
    ("Arbeitszylinder", "Power cylinder"),
    ("Sammler", "Plenum"),
    ("Zeit", "Time"),
    ("Kurbelwinkel", "Crank angle"),
    ("Fortschritt", "progress"),
    ("Kennwerte", "Metrics"),
    ("Bilanzfehler", "Balance error"),
    ("Anschleppkraft", "Cranking force"),
    ("Anschleppmoment", "Cranking torque"),
    ("Hubvolumen", "Displacement volume"),
    ("Positionen", "Positions"),
    ("Rueckwirkung", "Feedback"),
    ("Rückwirkung", "Feedback"),
    ("Zusammensetzung", "Composition"),
    ("Dynamik", "Dynamics"),
    ("Einzelplots", "individual plots"),
    ("vorwärts", "forward"),
    ("rückwärts", "reverse"),
    ("ueber", "over"),
)

GERMAN_MARKERS = re.compile(
    r"\b(?:Druck|Drücke|Temperatur(?:en)?|Wandwärme|Wandwaerme|Zylinder|Kompressor|"
    r"Massenstrom|Massenströme|Masse|Kolbenweg|Geschwindigkeit|Beschleunigung|"
    r"Einlass|Auslass|Öffnungsquerschnitt|Ventilhub|Zugeführte|Zugefuehrte|"
    r"Kraftstoff|Verbrennung|Spülung|Spuelung|Zeit|Kurbelwinkel|Kräfte)\b",
    re.IGNORECASE,
)


def english_text(value: str) -> str:
    text = value.replace("Ã¼", "ü").replace("Ã¶", "ö").replace("Ã¤", "ä").replace("Â²", "²").strip()
    if text in EXACT_TRANSLATIONS:
        return EXACT_TRANSLATIONS[text]
    for source, target in REPLACEMENTS:
        text = re.sub(rf"(?<!\w){re.escape(source)}(?!\w)", target, text)
    # Repair strings produced by older, substring-based normalizer revisions.
    text = text.replace("Masss", "Masses")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def signal_key(series: dict[str, Any]) -> str:
    return str(series.get("signal_key") or series.get("signal") or "").lower()


def is_pressure(key: str) -> bool:
    return bool(re.search(r"(?:^|_)(?:p_pa|pressure|p_bar)(?:_|$)", key))


def is_temperature(key: str) -> bool:
    return "_t_k" in key or "temperature" in key


def is_mass_flow(key: str) -> bool:
    return "mdot" in key or "mass_flow" in key or "massflow" in key


def is_geometry(key: str) -> bool:
    terms = ("area", "a_eff", "aeff", "opening", "lift", "slot_height", "volume", "_v_m3", "stroke", "piston_x", "piston_position", "distance_from_tdc")
    return any(term in key for term in terms)


def is_piston_motion(key: str) -> bool:
    terms = ("piston_x", "piston_v", "piston_a", "stroke_m", "distance_from_tdc", "free_piston_x", "free_piston_v", "free_piston_a", "oscillation_angle")
    return any(term in key for term in terms)


def is_added_energy(key: str) -> bool:
    return "added_energy" in key or "q_add" in key or "qdot_vibe" in key or "heat_release" in key


def flow_direction(key: str, label: str) -> str | None:
    text = f"{key} {label}".lower()
    inlet = ("inlet", "intake", "transfer", "receiver", "ambient_in", "mdot_in", "inflow", "_in_")
    outlet = ("outlet", "exhaust", "ambient_out", "mdot_out", "outflow", "_out_")
    if any(term in text for term in inlet):
        return "inlet"
    if any(term in text for term in outlet):
        return "outlet"
    return None


def cylinder_number(key: str, label: str) -> int | None:
    text = f"{key} {label}".lower()
    if re.search(r"(?:cylinder|cyl|zylinder)[ _-]*1\b", text):
        return 1
    if re.search(r"(?:cylinder|cyl|zylinder)[ _-]*2\b", text):
        return 2
    if re.search(r"(?:^|[_ \-])(?:cylinder|cyl|zylinder)(?:[_ \-]|$)", text):
        return 1
    return None


def series_style(series: dict[str, Any]) -> tuple[str, str, float]:
    key = signal_key(series)
    label = english_text(str(series.get("label") or ""))
    cyl = cylinder_number(key, label)
    direction = flow_direction(key, label)

    color = GRAY
    line_style = "-"
    line_width = 1.6

    if is_pressure(key):
        color = PRESSURE_C1 if cyl == 1 else PRESSURE_C2 if cyl == 2 else OUTLET_RED if direction == "outlet" else INLET_BLUE if direction == "inlet" else GRAY
        line_width = 1.8
    elif is_temperature(key):
        color = TEMPERATURE_C1 if cyl == 1 else TEMPERATURE_C2 if cyl == 2 else OUTLET_RED if direction == "outlet" else INLET_BLUE if direction == "inlet" else GRAY
        line_width = 1.8
    elif is_added_energy(key):
        color = ENERGY_RED
        line_width = 1.9
    elif cyl == 1:
        color = CYLINDER_1_LIGHT
    elif cyl == 2:
        color = CYLINDER_2_DARK

    if is_piston_motion(key):
        color = BLACK
        line_style = "--"
        line_width = 1.35
    elif is_mass_flow(key):
        line_style = "-."
        line_width = 1.45
        if direction == "inlet":
            color = INLET_BLUE
        elif direction == "outlet":
            color = OUTLET_RED
    elif is_geometry(key):
        line_style = "--"
        line_width = 1.05
        if direction == "inlet":
            color = INLET_BLUE
        elif direction == "outlet":
            color = OUTLET_RED

    return color, line_style, line_width


def normalize_series(series: dict[str, Any]) -> None:
    if isinstance(series.get("label"), str):
        series["label"] = english_text(series["label"])
    color, line_style, line_width = series_style(series)
    series["color"] = color
    series["line_style"] = line_style
    series["line_width"] = line_width


def walk_and_translate(node: Any) -> None:
    if isinstance(node, dict):
        for key, value in list(node.items()):
            if key in DISPLAY_KEYS and isinstance(value, str):
                node[key] = english_text(value)
            elif key == "title" and isinstance(value, str):
                node[key] = english_text(value)
            walk_and_translate(node[key])
    elif isinstance(node, list):
        for value in node:
            walk_and_translate(value)


def normalize_document(data: dict[str, Any]) -> None:
    walk_and_translate(data)
    data["style"] = {"default_line_width": 1.6}
    figures = data.get("figures")
    if not isinstance(figures, list):
        return
    for figure in figures:
        if not isinstance(figure, dict):
            continue
        figure.setdefault("rows", 1)
        figure.setdefault("cols", 1)
        subplots = figure.get("subplots")
        if not isinstance(subplots, list):
            continue
        for subplot in subplots:
            if not isinstance(subplot, dict):
                continue
            subplot["show_title"] = True
            y_axes = subplot.get("y_axes")
            if isinstance(y_axes, list):
                for axis in y_axes:
                    if isinstance(axis, dict):
                        axis["color"] = BLACK
                        if isinstance(axis.get("title"), str):
                            axis["title"] = english_text(axis["title"])
            series = subplot.get("series")
            if isinstance(series, list):
                for item in series:
                    if isinstance(item, dict):
                        normalize_series(item)


def collect_yaml_files(directories: list[Path]) -> list[Path]:
    return sorted({path.resolve() for directory in directories if directory.exists() for path in directory.rglob("*.yaml")})


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("directories", nargs="*", type=Path)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    directories = [path.resolve() for path in args.directories] if args.directories else list(DEFAULT_DIRS)
    files = collect_yaml_files(directories)
    changed = 0
    errors: list[str] = []
    german: list[str] = []
    for path in files:
        try:
            original = path.read_text(encoding="utf-8")
            data = yaml.safe_load(original)
            if not isinstance(data, dict):
                errors.append(f"{path}: root is not a mapping")
                continue
            normalize_document(data)
            rendered = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=140)
            yaml.safe_load(rendered)
            if GERMAN_MARKERS.search(rendered):
                german.append(str(path))
            if rendered != original:
                changed += 1
                if not args.check:
                    path.write_text(rendered, encoding="utf-8", newline="\n")
        except Exception as exc:
            errors.append(f"{path}: {exc}")
    print(f"files={len(files)} changed={changed} errors={len(errors)} german_markers={len(german)}")
    for item in errors:
        print(f"ERROR {item}")
    for item in german[:20]:
        print(f"GERMAN {item}")
    return 1 if errors or (args.check and changed) else 0


if __name__ == "__main__":
    raise SystemExit(main())
