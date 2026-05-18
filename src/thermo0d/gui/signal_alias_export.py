from __future__ import annotations

import csv
import math
from pathlib import Path
from typing import Any, Iterable

DEFAULT_SIGNAL_EXPORT_NAME = "thermo0d_signal_export_layout.csv"

_UNIT_CHOICES: dict[str, list[str]] = {
    "-": ["-"],
    "s": ["s", "ms", "us"],
    "deg": ["deg"],
    "kg": ["kg", "g", "mg"],
    "kg/s": ["kg/s", "g/s", "mg/s"],
    "m": ["m", "mm"],
    "m/s": ["m/s", "mm/s"],
    "m/s²": ["m/s²", "mm/s²"],
    "m²": ["m²", "cm²", "mm²"],
    "m³": ["m³", "L", "cm³", "mm³"],
    "m³/s": ["m³/s", "L/s", "cm³/s"],
    "Pa": ["Pa", "kPa", "bar", "MPa"],
    "K": ["K", "°C"],
    "J": ["J", "kJ"],
    "W": ["W", "kW"],
    "N": ["N", "kN"],
    "W/m²K": ["W/m²K", "kW/m²K"],
}


def allowed_target_units(source_unit: str | None) -> list[str]:
    unit = str(source_unit or "").strip()
    if not unit:
        return [""]
    return list(_UNIT_CHOICES.get(unit, [unit]))



def normalize_target_unit(source_unit: str | None, requested_unit: str | None) -> str:
    source = str(source_unit or "").strip()
    requested = str(requested_unit or "").strip()
    allowed = allowed_target_units(source)
    if requested and requested in allowed:
        return requested
    if source in allowed:
        return source
    return allowed[0] if allowed else source



def effective_display_name(row: dict[str, Any]) -> str:
    display_name = str(row.get("display_name") or "").strip()
    if display_name:
        return display_name
    default_name = str(row.get("default_name") or "").strip()
    if default_name:
        return default_name
    return str(row.get("key") or "").strip()



def is_export_enabled(row: dict[str, Any]) -> bool:
    return bool(row.get("export_enabled", False))



def build_export_header_rows(rows: Iterable[dict[str, Any]]) -> list[list[str]]:
    selected = [row for row in rows if is_export_enabled(row)]
    signal_names = [str(row.get("key") or "").strip() for row in selected]
    user_names = [effective_display_name(row) for row in selected]
    short_names = [str(row.get("short_name") or "").strip() for row in selected]
    units = [normalize_target_unit(str(row.get("unit") or ""), str(row.get("target_unit") or "")) for row in selected]
    return [signal_names, user_names, short_names, units]



def export_signal_layout_csv(rows: Iterable[dict[str, Any]], output_path: Path | str, *, delimiter: str = ";") -> Path:
    out = Path(output_path).expanduser().resolve()
    header_rows = build_export_header_rows(rows)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=delimiter)
        writer.writerows(header_rows)
    return out
