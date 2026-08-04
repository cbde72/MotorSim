from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import yaml

from thermo0d.app.paths import PathManager

DEFAULT_SIGNAL_CATALOG_NAME = "thermo0d_signal_catalog.yaml"
LEGACY_SIGNAL_CATALOG_NAMES = ("thermo0d_signal_catalog.yaml", "thermo0d_signal_catalog.json")
DEFAULT_SIGNAL_ALIAS_NAME = "thermo0d_signal_aliases.yaml"


_VOLUME_BASE_SPECS: list[tuple[str, str, str, str, str]] = [
    ("m_kg", "kg", "m", "volume_state", "Masse"),
    ("U_J", "J", "U", "volume_state", "Innere Energie"),
    ("m_burned_kg", "kg", "m_b", "volume_state", "Verbrannte Masse"),
    ("m_fresh_burned_kg", "kg", "m_b_new", "volume_state", "Neu verbrannte Masse"),
    ("m_residual_kg", "kg", "m_res", "volume_state", "Restgasmasse"),
    ("m_unburned_kg", "kg", "m_u", "volume_state", "Unverbrannte Masse"),
    ("m_fresh_gas_kg", "kg", "m_fresh", "volume_state", "Frischgasmasse"),
    ("burned_fraction_0to1", "-", "x_b", "volume_state", "Burned-Anteil"),
    ("share_residual_0to1", "-", "x_res", "volume_state", "Restgasanteil"),
    ("share_fresh_gas_0to1", "-", "x_fresh", "volume_state", "Frischgasanteil"),
    ("T_K", "K", "T", "volume_state", "Temperatur"),
    ("p_Pa", "Pa", "p", "volume_state", "Druck"),
    ("V_m3", "m³", "V", "volume_state", "Volumen"),
    ("dVdt_m3_per_s", "m³/s", "dV/dt", "volume_state", "Volumenänderungsrate"),
    ("theta_deg", "deg", "θ", "volume_state", "Kurbelwinkel"),
]

_CYLINDER_EXTRA_SPECS: list[tuple[str, str, str, str, str]] = [
    ("mdot_in_kg_per_s", "kg/s", "ṁ_in", "cylinder_balance", "Einströmender Massenstrom"),
    ("mdot_out_kg_per_s", "kg/s", "ṁ_out", "cylinder_balance", "Ausströmender Massenstrom"),
    ("A_eff_in_m2", "m²", "A_eff,in", "cylinder_balance", "Effektiver Einlassquerschnitt"),
    ("A_eff_out_m2", "m²", "A_eff,out", "cylinder_balance", "Effektiver Auslassquerschnitt"),
    ("enthalpy_in_W", "W", "Ĥ_in", "cylinder_balance", "Enthalpiestrom ein"),
    ("enthalpy_out_W", "W", "Ĥ_out", "cylinder_balance", "Enthalpiestrom aus"),
    ("wall_heat_W", "W", "Q̇_wall", "heat_transfer", "Zylinderwandwärme"),
    ("heat_transfer_power_W", "W", "Q̇_ht", "heat_transfer", "Wärmeleistung Zylinder"),
    ("htc_W_per_m2K", "W/m²K", "HTC", "heat_transfer", "Heat-Transfer-Coefficient"),
    ("added_energy_W", "W", "Q̇_add", "combustion", "Zugeführte Energie"),
    ("evaporation_sink_W", "W", "Q̇_evap", "evaporation", "Verdampfungsenthalpie-Senke"),
    ("piston_work_W", "W", "P_pV", "pv_work", "Kolbenarbeit"),
    ("wall_heat_cycle_J", "J", "Q_wall", "cycle_integral", "Zylinderwandwärme"),
    ("added_energy_cycle_J", "J", "Q_add", "cycle_integral", "Zugeführte Energie"),
    ("enthalpy_in_cycle_J", "J", "H_in", "cycle_integral", "Enthalpie ein"),
    ("enthalpy_out_cycle_J", "J", "H_out", "cycle_integral", "Enthalpie aus"),
    ("evaporation_sink_cycle_J", "J", "Q_evap", "cycle_integral", "Verdampfungsenthalpie-Senke"),
    ("piston_work_cycle_J", "J", "W_pV", "cycle_integral", "Kolbenarbeit"),
    ("indicated_power_W", "W", "P_i", "cycle_integral", "Innere Leistung"),
]

_FREE_PISTON_LOCAL_KINEMATICS_SPECS: list[tuple[str, str, str, str, str]] = [
    ("piston_x_m", "m", "x", "free_piston_local_kinematics", "Kolbenposition"),
    ("piston_distance_from_tdc_m", "m", "s", "free_piston_local_kinematics", "Hub ab OT"),
    ("piston_v_m_per_s", "m/s", "v", "free_piston_local_kinematics", "Kolbengeschwindigkeit"),
]

_CONNECTION_SPECS: list[tuple[str, str, str, str, str]] = [
    ("valve_lift_m", "m", "h_valve", "connection_geometry", "Ventilhub"),
    ("slot_height_m", "m", "h_slot", "connection_geometry", "Slot-Höhe"),
    ("A_geom_m2", "m²", "A_geom", "connection_geometry", "Geometrische Öffnungsfläche"),
    ("A_eff_forward_m2", "m²", "A_eff,fwd", "connection_geometry", "Effektiver Querschnitt vorwärts"),
    ("A_eff_reverse_m2", "m²", "A_eff,rev", "connection_geometry", "Effektiver Querschnitt rückwärts"),
    ("mdot_kg_per_s", "kg/s", "ṁ", "connection_flow", "Massenstrom"),
    ("mdot_residual_kg_per_s", "kg/s", "mdot_res", "connection_flow", "Restgas-Massenstrom"),
]

_GLOBAL_SIGNALS: list[tuple[str, str, str, str, str, str]] = [
    ("t_s", "s", "t", "global", "Zeit", "global"),
    ("cycle_index", "-", "cycle", "global", "Zyklusindex", "global"),
]

_FREE_PISTON_SPECS: list[tuple[str, str, str, str, str]] = [
    ("free_piston_x_m", "m", "x", "free_piston", "Kolbenposition"),
    ("free_piston_distance_from_tdc_m", "m", "s", "free_piston", "Abstand von TDC"),
    ("free_piston_v_m_per_s", "m/s", "v", "free_piston", "Kolbengeschwindigkeit"),
    ("free_piston_a_m_per_s2", "m/s²", "a", "free_piston", "Kolbenbeschleunigung"),
    ("free_piston_F_gas_N", "N", "F_gas", "free_piston", "Gasdruckkraft"),
    ("free_piston_F_bounce_N", "N", "F_bounce", "free_piston", "Bounce-Kraft"),
    ("free_piston_F_friction_N", "N", "F_fric", "free_piston", "Reibkraft"),
    ("free_piston_F_load_N", "N", "F_load", "free_piston", "Lastkraft"),
    ("free_piston_F_net_N", "N", "F_net", "free_piston", "Nettokraft"),
    ("free_piston_generator_power_W", "W", "P_gen", "free_piston", "Generatorleistung mechanisch"),
    ("free_piston_generator_electrical_power_W", "W", "P_el", "free_piston", "Generatorleistung elektrisch"),
    ("free_piston_generator_damping_eff_Ns_per_m", "Ns/m", "c_eff", "free_piston", "Effektive Generator-Dämpfung"),
    ("free_piston_generator_force_base_N", "N", "F_gen,base", "free_piston", "Generator-Grundkraft"),
    ("free_piston_generator_force_power_N", "N", "F_gen,P", "free_piston", "Generator-Leistungskraft"),
    ("free_piston_generator_assist_force_N", "N", "F_assist", "free_piston", "Anschleppkraft"),
    ("free_piston_generator_assist_torque_Nm", "Nm", "M_assist", "free_piston", "Anschleppmoment"),
    ("free_piston_generator_force_stop_N", "N", "F_gen,stop", "free_piston", "Generator-Schutzkraft"),
    ("free_piston_generator_distance_to_stop_m", "m", "d_stop", "free_piston", "Abstand zum aktiven Endanschlag"),
    ("free_piston_generator_midstroke_weight", "-", "w_mid", "free_piston", "Midstroke-Gewichtung"),
    ("bounce_volume_m3", "m³", "V_b", "free_piston", "Bounce-Volumen"),
    ("bounce_pressure_Pa", "Pa", "p_b", "free_piston", "Bounce-Druck"),
]


def _ordered_unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _load_mapping(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
    else:
        data = json.loads(text)
    return data if isinstance(data, dict) else {}


def _discover_project_dir(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / "Projekte").exists() and (candidate / "src").exists():
            return candidate / "Projekte"
    if (cur / "Projekte").exists():
        return cur / "Projekte"
    return cur


def _discover_config_files(project_dir: Path) -> list[Path]:
    files = [p for p in project_dir.glob("*.yaml") if p.is_file()] + [p for p in project_dir.glob("*.yml") if p.is_file()]
    variants = project_dir / "variants"
    if variants.exists():
        files += [p for p in variants.glob("*.yaml") if p.is_file()]
        files += [p for p in variants.glob("*.yml") if p.is_file()]
    return sorted(set(files), key=lambda p: (0 if p.parent == project_dir else 1, p.name.lower()))


def _csv_header(path: Path, sep: str) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=sep)
        try:
            return [str(x).strip() for x in next(reader)]
        except StopIteration:
            return []


def _separator_from_config(data: dict[str, Any]) -> str:
    post = data.get("postprocessing") if isinstance(data.get("postprocessing"), dict) else {}
    sep = post.get("csv_separator", ",")
    return str(sep) if sep else ","


def _csv_path_from_config(config_path: Path, data: dict[str, Any]) -> Path | None:
    post = data.get("postprocessing") if isinstance(data.get("postprocessing"), dict) else {}
    raw_csv = post.get("csv_path")
    if not raw_csv:
        return None
    return PathManager.resolve_output_file(
        config_path,
        configured_outdir=post.get("outdir"),
        configured_path=str(raw_csv),
        fallback_name="out.csv",
    )


def _volumes_and_connections(data: dict[str, Any]) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    pre = data.get("preprocessing") if isinstance(data.get("preprocessing"), dict) else {}
    volumes_raw = pre.get("volumes") if isinstance(pre.get("volumes"), list) else []
    conns_raw = pre.get("connections") if isinstance(pre.get("connections"), list) else []
    volumes: list[tuple[str, str]] = []
    conns: list[tuple[str, str]] = []
    for vol in volumes_raw:
        if isinstance(vol, dict) and vol.get("name"):
            volumes.append((str(vol["name"]), str(vol.get("type") or "")))
    for conn in conns_raw:
        if isinstance(conn, dict) and conn.get("name"):
            conns.append((str(conn["name"]), str(conn.get("type") or "")))
    return volumes, conns


def _signal_entry(
    key: str,
    unit: str,
    short_name: str,
    source: str,
    default_name: str,
    category: str,
    signal_family: str = "general",
    signal_kind: str = "state",
) -> dict[str, str]:
    return {
        "key": key,
        "unit": unit,
        "short_name": short_name,
        "source": source,
        "default_name": default_name,
        "display_name": default_name,
        "category": category,
        "signal_family": signal_family,
        "signal_kind": signal_kind,
    }


def _build_signal_entries(volume_defs: list[tuple[str, str]], connection_defs: list[tuple[str, str]], has_free_piston: bool = False) -> list[dict[str, str]]:
    entries: list[dict[str, str]] = []
    for key, unit, short_name, source, default_name, category in _GLOBAL_SIGNALS:
        entries.append(_signal_entry(key, unit, short_name, source, default_name, category, "global", "index" if key == "cycle_index" else "state"))
    for name, vol_type in volume_defs:
        for suffix, unit, short_name, source, default_name in _VOLUME_BASE_SPECS:
            entries.append(_signal_entry(f"{name}_{suffix}", unit, short_name, source, f"{name}: {default_name}", "volumes", "state", "state"))
        if has_free_piston and vol_type in {"cylinder", "bounce_chamber"}:
            for suffix, unit, short_name, source, default_name in _FREE_PISTON_LOCAL_KINEMATICS_SPECS:
                entries.append(_signal_entry(
                    f"{name}_{suffix}", unit, short_name, source,
                    f"{name}: {default_name}", "free_piston", "mechanics", "state",
                ))
        if vol_type == "cylinder":
            for suffix, unit, short_name, source, default_name in _CYLINDER_EXTRA_SPECS:
                entries.append(_signal_entry(
                    f"{name}_{suffix}",
                    unit,
                    short_name,
                    source,
                    f"{name}: {default_name}",
                    "energy" if "enthalpy" in suffix or suffix.endswith("_J") or suffix.endswith("_W") else "volumes",
                    "energy" if (suffix.endswith("_J") or suffix.endswith("_W") or "enthalpy" in suffix) else "mass_balance",
                    "cumulative" if suffix.endswith("_cycle_J") else ("rate" if suffix.endswith("_W") else "state"),
                ))
    for name, _conn_type in connection_defs:
        for suffix, unit, short_name, source, default_name in _CONNECTION_SPECS:
            entries.append(_signal_entry(
                f"{name}_{suffix}",
                unit,
                short_name,
                source,
                f"{name}: {default_name}",
                "connections",
                "flow" if suffix.endswith("kg_per_s") else "geometry",
                "rate" if suffix.endswith("kg_per_s") else "geometry",
            ))
    if has_free_piston:
        for key, unit, short_name, source, default_name in _FREE_PISTON_SPECS:
            entries.append(_signal_entry(key, unit, short_name, source, default_name, "free_piston", "mechanics", "state"))
    return entries


def _entry_map(entries: list[dict[str, str]]) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {}
    for entry in entries:
        out.setdefault(entry["key"], dict(entry))
    return out


def _default_aliases(headers: list[str], volume_defs: list[tuple[str, str]], connection_defs: list[tuple[str, str]]) -> list[str]:
    aliases: list[str] = [
        "theta_deg", "theta_local_deg", "p_cyl_pa", "p_cyl_bar", "V_m3", "V_cm3",
        "T_cyl_K", "T_cyl_C", "m_cyl_kg", "m_cyl_mg",
        "A_in_mm2", "A_ex_mm2", "mdot_in_kg_per_s", "mdot_ex_kg_per_s",
        "wall_heat", "added_energy", "enthalpy_in", "enthalpy_out", "piston_work",
    ]
    cyl_names = [name for name, kind in volume_defs if kind == "cylinder"]
    for cyl in cyl_names:
        aliases += [
            f"{cyl}_theta_deg", f"{cyl}_p_Pa", f"{cyl}_T_K", f"{cyl}_V_m3", f"{cyl}_m_kg",
            f"{cyl}_wall_heat_cycle_J", f"{cyl}_added_energy_cycle_J", f"{cyl}_enthalpy_in_cycle_J",
            f"{cyl}_enthalpy_out_cycle_J", f"{cyl}_piston_work_cycle_J",
        ]
    for name, _ in connection_defs:
        aliases += [
            f"{name}_opening", f"{name}_area", f"{name}_aeff", f"{name}_mdot",
            f"{name}_forward_area", f"{name}_reverse_area",
        ]
    return _ordered_unique(headers + aliases)


def _default_keys(headers: list[str], volume_defs: list[tuple[str, str]], connection_defs: list[tuple[str, str]]) -> list[str]:
    preferred: list[str] = ["t_s", "cycle_index"]
    cyl_names = [name for name, kind in volume_defs if kind == "cylinder"]
    if cyl_names:
        cyl = cyl_names[0]
        preferred += [
            f"{cyl}_theta_deg", f"{cyl}_p_Pa", f"{cyl}_T_K", f"{cyl}_V_m3", f"{cyl}_m_kg",
            f"{cyl}_mdot_in_kg_per_s", f"{cyl}_mdot_out_kg_per_s",
            f"{cyl}_A_eff_in_m2", f"{cyl}_A_eff_out_m2",
            f"{cyl}_wall_heat_cycle_J", f"{cyl}_added_energy_cycle_J",
            f"{cyl}_enthalpy_in_cycle_J", f"{cyl}_enthalpy_out_cycle_J", f"{cyl}_piston_work_cycle_J",
        ]
    for name, _ in connection_defs:
        for suffix in ("valve_lift_m", "slot_height_m", "A_geom_m2", "A_eff_forward_m2", "A_eff_reverse_m2", "mdot_kg_per_s", "mdot_residual_kg_per_s"):
            preferred.append(f"{name}_{suffix}")
    return [key for key in _ordered_unique(preferred) if key in headers]


def _build_groups(entries: dict[str, dict[str, str]]) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {
        "global": [],
        "volumes": [],
        "connections": [],
        "opening": [],
        "mass_flow": [],
        "energy": [],
        "thermal": [],
        "free_piston": [],
    }
    for key, meta in entries.items():
        groups[meta.get("category") or "connections"].append(key)
        if key.endswith(("_A_geom_m2", "_A_eff_forward_m2", "_A_eff_reverse_m2", "_A_eff_in_m2", "_A_eff_out_m2", "_valve_lift_m", "_slot_height_m")):
            groups["opening"].append(key)
        if "mdot" in key:
            groups["mass_flow"].append(key)
        if key.endswith(("_wall_heat_W", "_heat_transfer_power_W", "_htc_W_per_m2K", "_wall_heat_cycle_J", "_added_energy_W", "_added_energy_cycle_J", "_evaporation_sink_W", "_evaporation_sink_cycle_J")):
            groups["thermal"].append(key)
        if key.endswith(("_enthalpy_in_W", "_enthalpy_out_W", "_enthalpy_in_cycle_J", "_enthalpy_out_cycle_J", "_piston_work_W", "_piston_work_cycle_J", "_indicated_power_W", "_U_J")):
            groups["energy"].append(key)
    if any(key.startswith('free_piston_') or key.startswith('bounce_') for key in entries):
        groups.setdefault('free_piston', [])
        for key in entries:
            if key.startswith('free_piston_') or key.startswith('bounce_'):
                groups['free_piston'].append(key)
    return {key: _ordered_unique(value) for key, value in groups.items()}


def build_signal_catalog_for_project(project_dir: Path | str | None = None) -> dict[str, Any]:
    project = _discover_project_dir(Path(project_dir).resolve() if project_dir is not None else None) if project_dir is not None else _discover_project_dir()
    config_files = _discover_config_files(project)
    headers: list[str] = []
    volume_defs: list[tuple[str, str]] = []
    connection_defs: list[tuple[str, str]] = []
    source_files: list[str] = []
    has_free_piston = False
    for config_path in config_files:
        try:
            data = _load_mapping(config_path)
        except Exception:
            continue
        architecture = str(((data.get('modeling') if isinstance(data.get('modeling'), dict) else {}) or {}).get('architecture', '') or '').strip().lower()
        if architecture == 'free_piston':
            has_free_piston = True
        volumes, conns = _volumes_and_connections(data)
        volume_defs.extend(volumes)
        connection_defs.extend(conns)
        csv_path = _csv_path_from_config(config_path, data)
        if csv_path is not None and csv_path.exists():
            sep = _separator_from_config(data)
            headers.extend(_csv_header(csv_path, sep))
            source_files.append(str(csv_path.relative_to(project) if csv_path.is_relative_to(project) else csv_path))
    volume_defs = _ordered_unique([f"{name}|{kind}" for name, kind in volume_defs])
    volume_defs_typed = [(item.split("|", 1)[0], item.split("|", 1)[1]) for item in volume_defs]
    if has_free_piston and not any(kind == 'cylinder' for _, kind in volume_defs_typed):
        volume_defs_typed.append(('cylinder', 'cylinder'))
    connection_defs = _ordered_unique([f"{name}|{kind}" for name, kind in connection_defs])
    connection_defs_typed = [(item.split("|", 1)[0], item.split("|", 1)[1]) for item in connection_defs]
    generated_entries = _build_signal_entries(volume_defs_typed, connection_defs_typed, has_free_piston=has_free_piston)
    entry_map = _entry_map(generated_entries)
    for header in headers:
        entry_map.setdefault(header, _signal_entry(header, "", "", "csv_header", header, "connections", "derived", "derived"))
    ordered = _ordered_unique([entry["key"] for entry in generated_entries] + headers)
    metadata = {key: entry_map[key] for key in ordered if key in entry_map}
    catalog = {
        "format": "thermo0d-signal-catalog-v2",
        "minimal": ordered[: min(len(ordered), 18)] or ordered,
        "full": ordered,
        "full_only": ordered,
        "postprocessed_dataframe_columns": ordered,
        "plotting_series_aliases": _default_aliases(ordered, volume_defs_typed, connection_defs_typed),
        "default_plot_style_keys": _default_keys(ordered, volume_defs_typed, connection_defs_typed),
        "groups": _build_groups(metadata),
        "sources": source_files,
        "signal_metadata": metadata,
        "signal_entries": [metadata[key] for key in ordered if key in metadata],
    }
    return catalog


def _load_existing_alias_display_names(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    try:
        data = _load_mapping(path)
    except Exception:
        return {}
    rows = data.get("signals") if isinstance(data.get("signals"), list) else []
    out: dict[str, str] = {}
    for row in rows:
        if isinstance(row, dict) and row.get("key"):
            out[str(row["key"])] = str(row.get("display_name") or row.get("default_name") or row["key"])
    return out


def build_signal_alias_catalog_for_project(project_dir: Path | str | None = None, *, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    project = _discover_project_dir(Path(project_dir).resolve() if project_dir is not None else None) if project_dir is not None else _discover_project_dir()
    signal_catalog = catalog or build_signal_catalog_for_project(project)
    alias_path = project / DEFAULT_SIGNAL_ALIAS_NAME
    preserved_names = _load_existing_alias_display_names(alias_path)
    rows: list[dict[str, str]] = []
    for entry in signal_catalog.get("signal_entries", []):
        if not isinstance(entry, dict) or not entry.get("key"):
            continue
        row = dict(entry)
        row["display_name"] = preserved_names.get(str(row["key"]), str(row.get("display_name") or row.get("default_name") or row["key"]))
        rows.append(row)
    return {
        "format": "thermo0d-signal-aliases-v1",
        "signals": rows,
    }


def generate_signal_catalog_file(project_dir: Path | str | None = None, output_path: Path | str | None = None) -> Path:
    project = _discover_project_dir(Path(project_dir).resolve() if project_dir is not None else None) if project_dir is not None else _discover_project_dir()
    catalog = build_signal_catalog_for_project(project)
    out = Path(output_path) if output_path is not None else (project / DEFAULT_SIGNAL_CATALOG_NAME)
    if not out.is_absolute():
        out = (project / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(catalog, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out


def generate_signal_alias_file(project_dir: Path | str | None = None, output_path: Path | str | None = None) -> Path:
    project = _discover_project_dir(Path(project_dir).resolve() if project_dir is not None else None) if project_dir is not None else _discover_project_dir()
    catalog = build_signal_catalog_for_project(project)
    alias_catalog = build_signal_alias_catalog_for_project(project, catalog=catalog)
    out = Path(output_path) if output_path is not None else (project / DEFAULT_SIGNAL_ALIAS_NAME)
    if not out.is_absolute():
        out = (project / out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(yaml.safe_dump(alias_catalog, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return out
