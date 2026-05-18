from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Iterable

PA_TO_BAR = 1.0e-5
M3_TO_CM3 = 1.0e6
M2_TO_MM2 = 1.0e6
M_TO_MM = 1.0e3
KG_TO_MG = 1.0e6
KG_TO_G = 1.0e3
W_TO_KW = 1.0e-3
J_TO_KJ = 1.0e-3
MPS_TO_KMPH = 3.6


@dataclass(frozen=True, slots=True)
class ExportLayoutSpec:
    keys: list[str]
    display_names: list[str]
    short_names: list[str]
    display_units: list[str]


def convert_export_key_to_engineering_units(key: str) -> str:
    name = str(key)
    if name.endswith('_Pa'):
        return name[:-3] + '_bar'
    if name.endswith('_m3'):
        return name[:-3] + '_cm3'
    if name.endswith('_m2'):
        return name[:-3] + '_mm2'
    if name.endswith('_m'):
        return name[:-2] + '_mm'
    return name


def _convert_key_value(key: str, value):
    name = str(key)
    converted_name = convert_export_key_to_engineering_units(name)

    if name.endswith('_Pa'):
        return converted_name, float(value) * PA_TO_BAR
    if name.endswith('_m3'):
        return converted_name, float(value) * M3_TO_CM3
    if name.endswith('_m2'):
        return converted_name, float(value) * M2_TO_MM2
    if name.endswith('_m'):
        return converted_name, float(value) * M_TO_MM
    return converted_name, value


def convert_rows_to_engineering_units(rows: list[dict[str, float | int]]) -> list[dict[str, float | int]]:
    """
    Convert exported result rows to engineering units for file export.

    Converted suffixes:
      *_Pa -> *_bar
      *_m3 -> *_cm3
      *_m2 -> *_mm2
      *_m  -> *_mm

    Only exact suffixes are converted, so rates such as *_m3_per_s,
    *_m_per_s and accelerations remain untouched.
    """
    out: list[dict[str, float | int]] = []
    for row in rows:
        new_row = OrderedDict()
        for key, value in row.items():
            new_key, new_value = _convert_key_value(key, value)
            new_row[new_key] = new_value
        out.append(dict(new_row))
    return out


def _normalize_unit_text(unit: str | None) -> str:
    text = str(unit or '').strip()
    replacements = {
        'm^3': 'm³',
        'cm^3': 'cm³',
        'mm^2': 'mm²',
        'm^2': 'm²',
        'W/m2K': 'W/m²K',
        'kW/m2K': 'kW/m²K',
        'degC': '°C',
        '° C': '°C',
        'deg': 'deg',
    }
    return replacements.get(text, text)


def _source_unit_from_key(key: str) -> str:
    name = str(key)
    if name.endswith('_kg_per_s'):
        return 'kg/s'
    if name.endswith('_m3_per_s'):
        return 'm³/s'
    if name.endswith('_W_per_m2K'):
        return 'W/m²K'
    if name.endswith('_m_per_s2'):
        return 'm/s²'
    if name.endswith('_m_per_s'):
        return 'm/s'
    if name.endswith('_W'):
        return 'W'
    if name.endswith('_N'):
        return 'N'
    if name.endswith('_kg'):
        return 'kg'
    if name.endswith('_J'):
        return 'J'
    if name.endswith('_K'):
        return 'K'
    if name.endswith('_Pa'):
        return 'Pa'
    if name.endswith('_m3'):
        return 'm³'
    if name.endswith('_m2'):
        return 'm²'
    if name.endswith('_m'):
        return 'm'
    if name.endswith('_deg'):
        return 'deg'
    if name.endswith('_0to1'):
        return '-'
    if name == 't_s' or name.endswith('_t_s') or name.endswith('_time_s'):
        return 's'
    if name == 'cycle_index':
        return '-'
    return ''


def _convert_value_between_units(value, source_unit: str, target_unit: str):
    if value is None:
        return None
    src = _normalize_unit_text(source_unit)
    dst = _normalize_unit_text(target_unit)
    if not dst or dst == src:
        return value
    try:
        numeric = float(value)
    except Exception:
        return value

    conversions = {
        ('kg', 'mg'): lambda x: x * KG_TO_MG,
        ('kg', 'g'): lambda x: x * KG_TO_G,
        ('kg', 'kg'): lambda x: x,
        ('kg/s', 'mg/s'): lambda x: x * KG_TO_MG,
        ('kg/s', 'g/s'): lambda x: x * KG_TO_G,
        ('kg/s', 'kg/s'): lambda x: x,
        ('J', 'kJ'): lambda x: x * J_TO_KJ,
        ('J', 'J'): lambda x: x,
        ('W', 'kW'): lambda x: x * W_TO_KW,
        ('W', 'W'): lambda x: x,
        ('K', '°C'): lambda x: x - 273.15,
        ('K', 'K'): lambda x: x,
        ('Pa', 'bar'): lambda x: x * PA_TO_BAR,
        ('Pa', 'kPa'): lambda x: x * 1.0e-3,
        ('Pa', 'MPa'): lambda x: x * 1.0e-6,
        ('Pa', 'Pa'): lambda x: x,
        ('m³', 'cm³'): lambda x: x * M3_TO_CM3,
        ('m³', 'm³'): lambda x: x,
        ('m²', 'mm²'): lambda x: x * M2_TO_MM2,
        ('m²', 'm²'): lambda x: x,
        ('m', 'mm'): lambda x: x * M_TO_MM,
        ('m', 'cm'): lambda x: x * 1.0e2,
        ('m', 'm'): lambda x: x,
        ('m/s', 'km/h'): lambda x: x * MPS_TO_KMPH,
        ('m/s', 'm/s'): lambda x: x,
        ('m/s²', 'm/s²'): lambda x: x,
        ('W/m²K', 'W/m²K'): lambda x: x,
        ('N', 'N'): lambda x: x,
        ('deg', 'deg'): lambda x: x,
        ('s', 's'): lambda x: x,
        ('-', '-'): lambda x: x,
        ('', ''): lambda x: x,
    }
    func = conversions.get((src, dst))
    if func is None:
        return numeric
    return func(numeric)


def convert_rows_to_layout_units(rows: list[dict[str, object]], layout: ExportLayoutSpec) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    keys = list(layout.keys)
    units = list(layout.display_units)
    for row in rows:
        converted: OrderedDict[str, object] = OrderedDict()
        for idx, key in enumerate(keys):
            target_unit = units[idx] if idx < len(units) else ''
            source_unit = _source_unit_from_key(key)
            converted[key] = _convert_value_between_units(row.get(key), source_unit, target_unit)
        out.append(dict(converted))
    return out
