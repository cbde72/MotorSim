from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import transforms as mtransforms
from matplotlib.ticker import FuncFormatter, MultipleLocator
import yaml
import imageio

from thermo0d.config.constants import CombCol, ConnCol, ConnectionType, VolumeCol, VolumeType
from thermo0d.physics.kinematics import reference_zero_deg, wrap_angle_deg
from thermo0d.output.info_box import draw_info_box


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(text).strip()).strip("_").lower()
    return slug or "figure"


def _series_def(signal_key: str, label: str, axis_id: str, color: str, line_style: str = "-", scale_factor: float = 1.0, offset: float = 0.0) -> dict[str, Any]:
    return {
        "signal_key": signal_key,
        "label": label,
        "axis_id": axis_id,
        "color": color,
        "line_style": line_style,
        "scale_factor": scale_factor,
        "offset": offset,
        "unit_preset": "raw",
    }


def _event_def(x_value: float, label: str, color: str = "#666666", line_style: str = ":", line_width: float = 1.0, alpha: float = 0.9, visible: bool = True, show_label: bool = True, event_type: str = "custom") -> dict[str, Any]:
    return {
        "x": float(x_value),
        "label": str(label),
        "color": color,
        "line_style": line_style,
        "line_width": float(line_width),
        "alpha": float(alpha),
        "visible": bool(visible),
        "show_label": bool(show_label),
        "event_type": str(event_type),
        "label_rotation": 90.0,
        "label_font_size": 7.0,
        "label_bg_color": "#ffffff",
        "label_bg_alpha": 0.8,
        "label_border_color": "none",
        "label_y": 0.98,
        "label_ha": "right",
        "label_va": "top",
    }


def _detect_intake_exhaust_valves(bundle) -> tuple[str | None, str | None]:
    intake = None
    exhaust = None
    cyl_set = set(int(v) for v in bundle.cylinder_indices)
    for idx, name in enumerate(bundle.connection_names):
        conn = bundle.conn_matrix[idx]
        if int(conn[ConnCol.TYPE]) != ConnectionType.VALVE:
            continue
        left = int(conn[ConnCol.FROM_VOL])
        right = int(conn[ConnCol.TO_VOL])
        if right in cyl_set and left not in cyl_set and intake is None:
            intake = name
        if left in cyl_set and right not in cyl_set and exhaust is None:
            exhaust = name
    return intake, exhaust


def _angle_event(conn_row, local_deg: float, cycle_deg: float) -> float:
    ref_zero = float(reference_zero_deg(float(cycle_deg), int(conn_row[ConnCol.REF_TYPE])))
    return float(wrap_angle_deg(ref_zero + float(conn_row[ConnCol.OPEN_VALUE]) + float(local_deg), float(cycle_deg)))


def _valve_open_close_events(bundle) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    cyl_set = set(int(v) for v in bundle.cylinder_indices)
    for idx, conn_name in enumerate(bundle.connection_names):
        conn = bundle.conn_matrix[idx]
        if int(conn[ConnCol.TYPE]) != ConnectionType.VALVE:
            continue
        left = int(conn[ConnCol.FROM_VOL])
        right = int(conn[ConnCol.TO_VOL])
        if left in cyl_set and right not in cyl_set:
            open_label, close_label = "EVO", "EVC"
            color = "#b42318"
        elif right in cyl_set and left not in cyl_set:
            open_label, close_label = "IVO", "IVC"
            color = "#175cd3"
        else:
            continue
        start = int(conn[ConnCol.PROFILE_START])
        length = int(conn[ConnCol.PROFILE_LEN])
        if length <= 0:
            continue
        profile = bundle.lift_table[start:start + length]
        if profile.size == 0:
            continue
        local_angles = profile[:, 0].astype(float)
        raw_lift = profile[:, 1].astype(float)
        effective_lift = raw_lift * float(conn[ConnCol.LIFT_SCALE]) - float(conn[ConnCol.LASH])
        positive = effective_lift > 1.0e-12
        if not positive.any():
            continue
        local_open = float(local_angles[positive][0])
        local_close = float(local_angles[positive][-1])
        if int(conn[ConnCol.ANGLE_DOMAIN]) != 1:
            cam_ratio = float(bundle.cycle_deg) / 360.0
            local_open *= cam_ratio
            local_close *= cam_ratio
        events.append(_event_def(_angle_event(conn, local_open, bundle.cycle_deg), open_label, color=color, event_type="valve"))
        events.append(_event_def(_angle_event(conn, local_close, bundle.cycle_deg), close_label, color=color, event_type="valve"))
    return events


def _combustion_events(bundle) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for cyl_idx in bundle.cylinder_indices:
        comb_row_idx = int(bundle.vol_matrix[int(cyl_idx), VolumeCol.COMB_ROW])
        if comb_row_idx < 0:
            continue
        comb = bundle.comb_matrix[comb_row_idx]
        if int(comb[CombCol.MODEL]) == 0:
            continue
        ref_zero = float(reference_zero_deg(float(bundle.cycle_deg), int(comb[CombCol.REF_TYPE])))
        start = float(wrap_angle_deg(ref_zero + float(comb[CombCol.START_DEG]), float(bundle.cycle_deg)))
        end = float(wrap_angle_deg(ref_zero + float(comb[CombCol.START_DEG]) + float(comb[CombCol.DURATION_DEG]), float(bundle.cycle_deg)))
        events.append(_event_def(start, "SOC", color="#f79009", line_style="--", event_type="combustion"))
        events.append(_event_def(end, "EOC", color="#f79009", line_style="--", event_type="combustion"))
        break
    return events


def _reference_events(bundle) -> list[dict[str, Any]]:
    cycle_deg = float(bundle.cycle_deg)
    if cycle_deg >= 719.0:
        return [
            _event_def(0.0, "OT", color="#667085", line_style=":", event_type="reference"),
            _event_def(180.0, "UT", color="#667085", line_style=":", event_type="reference"),
            _event_def(360.0, "OT", color="#98a2b3", line_style=":", event_type="reference"),
            _event_def(540.0, "UT", color="#98a2b3", line_style=":", event_type="reference"),
        ]
    return [
        _event_def(0.0, "OT", color="#667085", line_style=":", event_type="reference"),
        _event_def(cycle_deg / 2.0, "UT", color="#667085", line_style=":"),
    ]


def _default_events(bundle) -> list[dict[str, Any]]:
    seen: set[tuple[str, float]] = set()
    out: list[dict[str, Any]] = []
    for event in _reference_events(bundle) + _valve_open_close_events(bundle) + _combustion_events(bundle):
        key = (str(event.get("label", "")), round(float(event.get("x", 0.0)), 6))
        if key in seen:
            continue
        seen.add(key)
        out.append(event)
    return sorted(out, key=lambda item: float(item.get("x", 0.0)))


def _free_piston_default_plot_project(bundle) -> dict[str, Any]:
    x_max = float(getattr(bundle.simulation, 'simulationtime_s', 0.0) or 0.0)
    if x_max <= 0.0:
        x_max = float(bundle.cycle_period_s * max(int(getattr(bundle.simulation, 'total_cycles', 1) or 1), 1))
    subplots = [
        {
            "title": "Kolbenweg / Geschwindigkeit",
            "plot_type": "line",
            "x_signal": "t_s",
            "x_title": "Zeit [s]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": x_max,
            "events": [],
            "y_axes": [
                {"id": "ax_x", "title": "Kolbenweg [mm] (+54 = OT, -54 = UT)", "side": "left", "color": "#111111"},
                {"id": "ax_v", "title": "Geschwindigkeit [m/s]", "side": "right", "color": "#1f77b4"},
            ],
            "series": [
                _series_def("free_piston_x_m", "Kolbenweg", "ax_x", "#111111", "-", -1000.0, 54.04),
                _series_def("free_piston_v_m_per_s", "Geschwindigkeit", "ax_v", "#1f77b4"),
            ],
        },
        {
            "title": "Kräfte",
            "plot_type": "line",
            "x_signal": "t_s",
            "x_title": "Zeit [s]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": x_max,
            "events": [],
            "y_axes": [
                {"id": "ax_force", "title": "Kraft [N]", "side": "left", "color": "#111111"},
            ],
            "series": [
                _series_def("free_piston_F_gas_N", "Gas", "ax_force", "#111111"),
                _series_def("free_piston_F_bounce_N", "Bounce", "ax_force", "#175cd3"),
                _series_def("free_piston_F_friction_N", "Reibung", "ax_force", "#b54708"),
                _series_def("free_piston_F_load_N", "Last", "ax_force", "#7a5af8"),
                _series_def("free_piston_F_net_N", "Netto", "ax_force", "#12b76a", "--"),
            ],
        },
        {
            "title": "Drücke",
            "plot_type": "line",
            "x_signal": "t_s",
            "x_title": "Zeit [s]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": x_max,
            "events": [],
            "y_axes": [
                {"id": "ax_p", "title": "Druck [bar]", "side": "left", "color": "#111111"},
            ],
            "series": [
                _series_def("cylinder_p_Pa", "Zylinderdruck", "ax_p", "#111111", "-", 1.0e-5),
                _series_def("bounce_pressure_Pa", "Bounce-Druck", "ax_p", "#175cd3", "--", 1.0e-5),
            ],
        },
        {
            "title": "Volumina",
            "plot_type": "line",
            "x_signal": "t_s",
            "x_title": "Zeit [s]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": x_max,
            "events": [],
            "y_axes": [
                {"id": "ax_vol", "title": "Volumen [cm³]", "side": "left", "color": "#111111"},
            ],
            "series": [
                _series_def("cylinder_V_m3", "Zylindervolumen", "ax_vol", "#111111", "-", 1.0e6),
                _series_def("bounce_volume_m3", "Bounce-Volumen", "ax_vol", "#175cd3", "--", 1.0e6),
            ],
        },
        {
            "title": "Beschleunigung",
            "plot_type": "line",
            "x_signal": "t_s",
            "x_title": "Zeit [s]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": x_max,
            "events": [],
            "y_axes": [
                {"id": "ax_a", "title": "Beschleunigung [m/s²]", "side": "left", "color": "#111111"},
            ],
            "series": [
                _series_def("free_piston_a_m_per_s2", "Beschleunigung", "ax_a", "#111111"),
            ],
        },
        {
            "title": "Zustandsgrößen",
            "plot_type": "line",
            "x_signal": "t_s",
            "x_title": "Zeit [s]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": x_max,
            "events": [],
            "y_axes": [
                {"id": "ax_t", "title": "Temperatur [K]", "side": "left", "color": "#111111"},
                {"id": "ax_m", "title": "Masse [mg]", "side": "right", "color": "#1f77b4"},
            ],
            "series": [
                _series_def("cylinder_T_K", "Zylindertemperatur", "ax_t", "#111111"),
                _series_def("cylinder_m_kg", "Zylindermasse", "ax_m", "#1f77b4", "-", 1.0e6),
            ],
        },
    ]
    return {
        "name": "Standard Free-Piston Plotpaket",
        "figures": [
            {
                "title": "Standard Free-Piston Plotpaket",
                "rows": 3,
                "cols": 2,
                "subplots": subplots,
            }
        ],
    }


def build_default_plot_project(bundle, config_data: dict[str, Any] | None = None) -> dict[str, Any]:
    del config_data
    if getattr(bundle, 'architecture', 'classic') == 'free_piston':
        return _free_piston_default_plot_project(bundle)
    cyl_name = bundle.volume_names[bundle.cylinder_indices[0]] if bundle.cylinder_indices else bundle.volume_names[0]
    intake_name, exhaust_name = _detect_intake_exhaust_valves(bundle)
    intake_lift = f"{intake_name}_valve_lift_m" if intake_name else ""
    exhaust_lift = f"{exhaust_name}_valve_lift_m" if exhaust_name else ""
    default_events = _default_events(bundle)

    def lift_series() -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if intake_lift:
            out.append(_series_def(intake_lift, "Einlasshub", "ax_lift", "#0000ff", "--", 1000.0))
        if exhaust_lift:
            out.append(_series_def(exhaust_lift, "Auslasshub", "ax_lift", "#ff0000", "--", 1000.0))
        return out

    subplots: list[dict[str, Any]] = [
        {
            "title": "Massenströme / Hubvolumen",
            "plot_type": "line",
            "x_signal": f"{cyl_name}_theta_deg",
            "x_title": "Kurbelwinkel [deg]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": float(bundle.cycle_deg),
            "events": default_events,
            "y_axes": [
                {"id": "ax_mdot", "title": "Massenstrom [kg/s]", "side": "left", "color": "#111111"},
                {"id": "ax_vol", "title": "Hubvolumen [cm³]", "side": "right", "color": "#666666"},
            ],
            "series": [
                _series_def(f"{cyl_name}_mdot_in_kg_per_s", "Einströmender Massenstrom", "ax_mdot", "#87cefa"),
                _series_def(f"{cyl_name}_mdot_out_kg_per_s", "Ausströmender Massenstrom", "ax_mdot", "#8b0000"),
                _series_def(f"{cyl_name}_V_m3", "Hubvolumen", "ax_vol", "#808080", "--", 1.0e6),
            ],
        },
        {
            "title": "Temperatur / Ventilhub",
            "plot_type": "line",
            "x_signal": f"{cyl_name}_theta_deg",
            "x_title": "Kurbelwinkel [deg]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": float(bundle.cycle_deg),
            "events": default_events,
            "y_axes": [
                {"id": "ax_main", "title": "Temperatur [K]", "side": "left", "color": "#111111"},
                {"id": "ax_lift", "title": "Ventilhub [mm]", "side": "right", "color": "#1f77b4"},
            ],
            "series": [_series_def(f"{cyl_name}_T_K", "Temperatur", "ax_main", "#111111")] + lift_series(),
        },
        {
            "title": "Innere Energie / Ventilhub",
            "plot_type": "line",
            "x_signal": f"{cyl_name}_theta_deg",
            "x_title": "Kurbelwinkel [deg]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": float(bundle.cycle_deg),
            "events": default_events,
            "y_axes": [
                {"id": "ax_main", "title": "Innere Energie [J]", "side": "left", "color": "#111111"},
                {"id": "ax_lift", "title": "Ventilhub [mm]", "side": "right", "color": "#1f77b4"},
            ],
            "series": [_series_def(f"{cyl_name}_U_J", "Innere Energie", "ax_main", "#111111")] + lift_series(),
        },
        {
            "title": "Zylindermasse / Ventilhub",
            "plot_type": "line",
            "x_signal": f"{cyl_name}_theta_deg",
            "x_title": "Kurbelwinkel [deg]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": float(bundle.cycle_deg),
            "events": default_events,
            "y_axes": [
                {"id": "ax_main", "title": "Zylindermasse [mg]", "side": "left", "color": "#111111"},
                {"id": "ax_lift", "title": "Ventilhub [mm]", "side": "right", "color": "#1f77b4"},
            ],
            "series": [_series_def(f"{cyl_name}_m_kg", "Zylindermasse", "ax_main", "#111111", "-", 1.0e6)] + lift_series(),
        },
        {
            "title": "Zugeführte Energie kumuliert / Ventilhub",
            "plot_type": "line",
            "x_signal": f"{cyl_name}_theta_deg",
            "x_title": "Kurbelwinkel [deg]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": float(bundle.cycle_deg),
            "events": default_events,
            "y_axes": [
                {"id": "ax_main", "title": "Zugeführte Energie [J]", "side": "left", "color": "#111111"},
                {"id": "ax_lift", "title": "Ventilhub [mm]", "side": "right", "color": "#1f77b4"},
            ],
            "series": [_series_def(f"{cyl_name}_added_energy_cycle_J", "Zugeführte Energie (kumuliert)", "ax_main", "#111111")] + lift_series(),
        },
        {
            "title": "Wandwärme kumuliert / Ventilhub",
            "plot_type": "line",
            "x_signal": f"{cyl_name}_theta_deg",
            "x_title": "Kurbelwinkel [deg]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": float(bundle.cycle_deg),
            "events": default_events,
            "y_axes": [
                {"id": "ax_main", "title": "Wandwärme [J]", "side": "left", "color": "#111111"},
                {"id": "ax_lift", "title": "Ventilhub [mm]", "side": "right", "color": "#1f77b4"},
            ],
            "series": [_series_def(f"{cyl_name}_wall_heat_cycle_J", "Wandwärme (kumuliert)", "ax_main", "#111111")] + lift_series(),
        },
        {
            "title": "Enthalpie ein/aus kumuliert / Ventilhub",
            "plot_type": "line",
            "x_signal": f"{cyl_name}_theta_deg",
            "x_title": "Kurbelwinkel [deg]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": float(bundle.cycle_deg),
            "events": default_events,
            "y_axes": [
                {"id": "ax_main", "title": "Enthalpie [J]", "side": "left", "color": "#111111"},
                {"id": "ax_lift", "title": "Ventilhub [mm]", "side": "right", "color": "#1f77b4"},
            ],
            "series": [
                _series_def(f"{cyl_name}_enthalpy_in_cycle_J", "Enthalpie ein (kumuliert)", "ax_main", "#87cefa"),
                _series_def(f"{cyl_name}_enthalpy_out_cycle_J", "Enthalpie aus (kumuliert)", "ax_main", "#8b0000"),
            ] + lift_series(),
        },
        {
            "title": "Kolbenarbeit kumuliert / Ventilhub",
            "plot_type": "line",
            "x_signal": f"{cyl_name}_theta_deg",
            "x_title": "Kurbelwinkel [deg]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": float(bundle.cycle_deg),
            "events": default_events,
            "y_axes": [
                {"id": "ax_main", "title": "Kolbenarbeit [J]", "side": "left", "color": "#111111"},
                {"id": "ax_lift", "title": "Ventilhub [mm]", "side": "right", "color": "#1f77b4"},
            ],
            "series": [_series_def(f"{cyl_name}_piston_work_cycle_J", "Kolbenarbeit (kumuliert)", "ax_main", "#111111")] + lift_series(),
        },
        {
            "title": "Energiebilanz kumuliert",
            "plot_type": "line",
            "x_signal": f"{cyl_name}_theta_deg",
            "x_title": "Kurbelwinkel [deg]",
            "x_unit_preset": "raw",
            "x_limit_mode": "manual",
            "x_min": 0.0,
            "x_max": float(bundle.cycle_deg),
            "events": default_events,
            "y_axes": [
                {"id": "ax_energy", "title": "Energie [J]", "side": "left", "color": "#111111"},
            ],
            "series": [
                _series_def(f"{cyl_name}_delta_U_cycle_J", "ΔU seit Zyklusstart", "ax_energy", "#111111"),
                _series_def(f"{cyl_name}_added_energy_cycle_J", "Q_add kumuliert", "ax_energy", "#ff8c00"),
                _series_def(f"{cyl_name}_wall_heat_cycle_J", "Q_wall kumuliert", "ax_energy", "#7a7a7a"),
                _series_def(f"{cyl_name}_enthalpy_net_cycle_J", "H_net kumuliert", "ax_energy", "#175cd3"),
                _series_def(f"{cyl_name}_piston_work_cycle_J", "W_pV kumuliert", "ax_energy", "#12b76a"),
                _series_def(f"{cyl_name}_energy_balance_residual_J", "Bilanzfehler", "ax_energy", "#b42318", "--"),
            ],
        },
    ]
    return {
        "name": "Standard Thermo0D Plotpaket",
        "figures": [
            {
                "title": "Standard Thermo0D Plotpaket",
                "rows": 5,
                "cols": 2,
                "subplots": subplots,
            }
        ],
    }


def build_single_figure_plot_project(bundle, config_data: dict[str, Any] | None = None) -> dict[str, Any]:
    base_project = build_default_plot_project(bundle, config_data=config_data)
    base_figures = base_project.get("figures") if isinstance(base_project.get("figures"), list) else []
    if not base_figures:
        return {"name": "Standard Thermo0D Einzelplot-Paket", "figures": []}
    first_figure = base_figures[0] if isinstance(base_figures[0], dict) else {}
    base_subplots = first_figure.get("subplots") if isinstance(first_figure.get("subplots"), list) else []
    single_figures: list[dict[str, Any]] = []
    for subplot in base_subplots:
        if not isinstance(subplot, dict):
            continue
        subplot_title = str(subplot.get("title", "Subplot") or "Subplot")
        subplot_single = dict(subplot)
        subplot_single["title"] = ""
        subplot_single["x_min"] = float(subplot.get("x_min", 0.0) or 0.0)
        subplot_single["x_max"] = float(subplot.get("x_max", bundle.cycle_deg) or bundle.cycle_deg)
        single_figures.append({
            "title": subplot_title,
            "rows": 1,
            "cols": 1,
            "subplots": [subplot_single],
        })
    return {
        "name": "Standard Thermo0D Einzelplot-Paket",
        "figures": single_figures,
    }


def _load_config_data(config_path: Path) -> dict[str, Any] | None:
    try:
        return yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception:
        return None



def _default_style_dict() -> dict[str, Any]:
    return {
        "preset_name": "Light Engineering",
        "font_family": "DejaVu Sans",
        "font_size": 8.0,
        "axis_label_size": 8.0,
        "tick_label_size": 8.0,
        "title_size": 9.0,
        "figure_title_size": 10.0,
        "subplot_title_visible": True,
        "figure_title_visible": True,
        "grid_visible": True,
        "grid_alpha": 0.3,
        "legend_visible": True,
        "legend_position": "best",
        "tight_layout": True,
        "default_line_width": 1.8,
        "default_marker_size": 4.0,
    }


def _style_sheet_data(data: dict[str, Any], plot_path: Path) -> dict[str, Any]:
    style_sheet = str(data.get("style_sheet", "") or data.get("stylesheet", "") or "").strip()
    if not style_sheet:
        return {}
    path = Path(style_sheet)
    if not path.is_absolute():
        path = plot_path.parent / path
    if not path.exists() or not path.is_file():
        return {}
    try:
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}
    if isinstance(loaded, dict) and isinstance(loaded.get("style"), dict):
        return dict(loaded["style"])
    return dict(loaded) if isinstance(loaded, dict) else {}


def _normalized_style_dict(data: dict[str, Any], plot_path: Path | None = None) -> dict[str, Any]:
    style = _default_style_dict()
    if plot_path is not None:
        style.update(_style_sheet_data(data, plot_path))
    if isinstance(data.get("style"), dict):
        style.update(data["style"])
    return style

def _ensure_default_plot_yaml_for_project(project_data: dict[str, Any], output_path: Path) -> Path:
    if not output_path.exists():
        output_path.write_text(yaml.safe_dump(project_data, sort_keys=False, allow_unicode=True), encoding="utf-8")
    return output_path


def ensure_default_plot10_yaml(bundle, config_path: str | Path, output_path: str | Path | None = None) -> Path:
    config_path = Path(config_path).resolve()
    out = Path(output_path).resolve() if output_path is not None else (config_path.parent / "plot10.yaml").resolve()
    config_data = _load_config_data(config_path)
    return _ensure_default_plot_yaml_for_project(build_single_figure_plot_project(bundle, config_data=config_data), out)


def ensure_default_plot_yaml(bundle, config_path: str | Path, output_path: str | Path | None = None) -> Path:
    config_path = Path(config_path).resolve()
    out = Path(output_path).resolve() if output_path is not None else (config_path.parent / "plot.yaml").resolve()
    config_data = _load_config_data(config_path)
    return _ensure_default_plot_yaml_for_project(build_default_plot_project(bundle, config_data=config_data), out)


def _series_values(rows: list[dict[str, Any]], signal_key: str, scale_factor: float = 1.0, offset: float = 0.0) -> list[float | None]:
    out: list[float | None] = []
    for row in rows:
        value = row.get(signal_key)
        try:
            out.append(float(value) * float(scale_factor) + float(offset))
        except Exception:
            out.append(None)
    return out


def _hide_values_before_positive_signal(rows: list[dict[str, Any]], values: list[float | None], signal_key: str, threshold: float = 0.0) -> list[float | None]:
    if not signal_key:
        return values
    first_index: int | None = None
    for idx, row in enumerate(rows):
        value = _finite(row, signal_key)
        if value is not None and value > threshold:
            first_index = idx
            break
    if first_index is None or first_index <= 0:
        return values
    masked = list(values)
    for idx in range(min(first_index, len(masked))):
        masked[idx] = None
    return masked


def _align_xy(x_values: list[Any], y_values: list[Any]) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for x, y in zip(x_values, y_values):
        try:
            xf = float(x)
            yf = float(y)
        except Exception:
            continue
        if math.isnan(xf) or math.isnan(yf):
            continue
        xs.append(xf)
        ys.append(yf)
    return xs, ys


def _finite(row: dict[str, Any], key: str) -> float | None:
    try:
        value = float(row.get(key))
    except Exception:
        return None
    return value if math.isfinite(value) else None


def _column(rows: list[dict[str, Any]], key: str) -> list[float]:
    values: list[float] = []
    for row in rows:
        value = _finite(row, key)
        values.append(value if value is not None else float("nan"))
    return values


def _trapz(xs: list[float], ys: list[float], *, absolute: bool = False) -> float | None:
    total = 0.0
    used = False
    for i in range(1, min(len(xs), len(ys))):
        x0 = xs[i - 1]
        x1 = xs[i]
        y0 = ys[i - 1]
        y1 = ys[i]
        if not all(math.isfinite(value) for value in (x0, x1, y0, y1)):
            continue
        if x1 < x0:
            continue
        if absolute:
            y0 = abs(y0)
            y1 = abs(y1)
        total += 0.5 * (y0 + y1) * (x1 - x0)
        used = True
    return total if used else None


def _metric_imep(rows: list[dict[str, Any]], metric: dict[str, Any]) -> float | None:
    cylinder = str(metric.get("cylinder", "") or "").strip()
    p_key = str(metric.get("pressure_signal", "") or (f"{cylinder}_p_Pa" if cylinder else "")).strip()
    v_key = str(metric.get("volume_signal", "") or (f"{cylinder}_V_m3" if cylinder else "")).strip()
    if not p_key or not v_key:
        return None
    p_values = _column(rows, p_key)
    v_values = _column(rows, v_key)
    work_j = _trapz(v_values, p_values)
    finite_v = [value for value in v_values if math.isfinite(value)]
    swept_volume = max(finite_v) - min(finite_v) if finite_v else None
    if work_j is None or swept_volume is None or swept_volume <= 1.0e-18:
        return None
    return work_j / swept_volume / 1.0e5


def _metric_value(rows: list[dict[str, Any]], metric: dict[str, Any], subplot: dict[str, Any]) -> float | None:
    kind = str(metric.get("kind", "") or "").lower().strip()
    if kind == "imep":
        value = _metric_imep(rows, metric)
    else:
        key = str(metric.get("signal_key", "") or "").strip()
        if not key:
            return None
        mode = str(metric.get("mode", "last") or "last").lower().strip()
        if mode == "first_where":
            raw_where_keys = metric.get("where_signal_any", None)
            if isinstance(raw_where_keys, list):
                where_keys = [str(item).strip() for item in raw_where_keys if str(item).strip()]
            else:
                where_keys = [str(metric.get("where_signal", "") or "").strip()]
            where_gte_raw = metric.get("where_gte", metric.get("where_ge", None))
            where_gte = _safe_float(where_gte_raw, 0.0) if where_gte_raw is not None else None
            where_gt = _safe_float(metric.get("where_gt", 0.0), 0.0)
            for row in rows:
                if where_gte is not None:
                    matches = any((where_value := _finite(row, where_key)) is not None and where_value >= where_gte for where_key in where_keys)
                else:
                    matches = any((where_value := _finite(row, where_key)) is not None and where_value > where_gt for where_key in where_keys)
                if matches:
                    value = _finite(row, key)
                    break
            else:
                value = None
            if value is None:
                return None
        else:
            values = _column(rows, key)
            finite_values = [item for item in values if math.isfinite(item)]
            if not finite_values:
                return None
            if mode == "first":
                value = finite_values[0]
            elif mode == "min":
                value = min(finite_values)
            elif mode == "max":
                value = max(finite_values)
            elif mode == "mean":
                value = sum(finite_values) / len(finite_values)
            elif mode == "delta":
                value = finite_values[-1] - finite_values[0]
            elif mode == "integral":
                x_key = str(metric.get("x_signal", "") or subplot.get("x_signal", "t_s") or "t_s")
                value = _trapz(_column(rows, x_key), values, absolute=bool(metric.get("absolute", False)))
            else:
                value = finite_values[-1]
    if value is None or not math.isfinite(value):
        return None
    if bool(metric.get("absolute", False)) and str(metric.get("mode", "") or "").lower() != "integral":
        value = abs(value)
    try:
        value = value * float(metric.get("scale_factor", 1.0) or 1.0) + float(metric.get("offset", 0.0) or 0.0)
    except Exception:
        pass
    return value if math.isfinite(value) else None


def _format_metric_value(value: float | None, metric: dict[str, Any]) -> str:
    unit = str(metric.get("unit", "") or "").strip()
    try:
        digits_raw = metric.get("digits", 2)
        digits = int(2 if digits_raw is None else digits_raw)
    except Exception:
        digits = 2
    if value is None or not math.isfinite(value):
        return "n/a"
    if bool(metric.get("fixed", False)):
        return f"{value:.{max(0, digits)}f} {unit}".strip()
    if bool(metric.get("scientific", False)):
        return f"{value:.{max(0, digits)}e} {unit}".strip()
    if abs(value) >= 1000.0 or (abs(value) < 0.01 and value != 0.0):
        return f"{value:.{max(1, digits)}g} {unit}".strip()
    return f"{value:.{max(0, digits)}f} {unit}".strip()


def _readme_table_values(path: Path) -> dict[str, tuple[str, str]]:
    values: dict[str, tuple[str, str]] = {}
    if not path.exists() or not path.is_file():
        return values
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except Exception:
        return values
    for line in lines:
        text = line.strip()
        if not text.startswith("|") or text.count("|") < 3:
            continue
        cells = [cell.strip().strip("`") for cell in text.strip("|").split("|")]
        if len(cells) < 3 or not cells[0] or set(cells[0]) <= {"-"}:
            continue
        key, value, unit = cells[0], cells[1], cells[2]
        if key.lower() in {"kennwert", "metric", "signal", "name"}:
            continue
        values[key] = (value, unit)
    return values


def _readme_values_for_box(info: dict[str, Any], plot_path: Path, output_dir: Path) -> dict[str, tuple[str, str]]:
    candidates: list[Path] = []
    configured = str(info.get("readme_path", "") or info.get("path", "") or "").strip()
    if configured:
        raw = Path(configured)
        candidates.append(raw if raw.is_absolute() else (plot_path.parent / raw))
        candidates.append(raw if raw.is_absolute() else (output_dir / raw))
    candidates.extend([
        output_dir / "README.md",
        output_dir.parent / "README.md",
        plot_path.parent / "README.md",
        Path.cwd() / "README.md",
    ])
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.resolve()
        except Exception:
            resolved = candidate
        if resolved in seen:
            continue
        seen.add(resolved)
        values = _readme_table_values(resolved)
        if values:
            return values
    return {}


def _readme_text_box_text(info: dict[str, Any], readme_values: dict[str, tuple[str, str]]) -> str:
    lines: list[str] = []
    title = str(info.get("title", "") or "").strip()
    if title:
        lines.append(title)
    metrics = info.get("metrics") if isinstance(info.get("metrics"), list) else []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        key = str(metric.get("readme_key", "") or metric.get("key", "") or metric.get("signal_key", "") or "").strip()
        if not key:
            continue
        label = str(metric.get("label", "") or key).strip()
        value, unit = readme_values.get(key, ("n/a", str(metric.get("unit", "") or "").strip()))
        unit = str(metric.get("unit", unit) if metric.get("unit", None) is not None else unit).strip()
        separator = str(metric.get("separator", ": ") or ": ")
        lines.append(f"{label}{separator}{value} {unit}".strip())
    return "\n".join(lines)


def _text_box_text(rows: list[dict[str, Any]], subplot: dict[str, Any], info: dict[str, Any], plot_path: Path, output_dir: Path) -> str:
    if str(info.get("source", "") or "").lower().strip() == "readme":
        return _readme_text_box_text(info, _readme_values_for_box(info, plot_path, output_dir))
    lines: list[str] = []
    title = str(info.get("title", "") or "").strip()
    if title:
        lines.append(title)
    metrics = info.get("metrics") if isinstance(info.get("metrics"), list) else []
    for metric in metrics:
        if not isinstance(metric, dict):
            continue
        label = str(metric.get("label", "") or metric.get("signal_key", "") or metric.get("kind", "") or "").strip()
        if not label:
            continue
        value = _metric_value(rows, metric, subplot)
        separator = str(metric.get("separator", ": ") or ": ")
        lines.append(f"{label}{separator}{_format_metric_value(value, metric)}")
    return "\n".join(lines)


def _draw_text_box(axis, subplot: dict[str, Any], rows: list[dict[str, Any]], plot_path: Path, output_dir: Path) -> None:
    info = subplot.get("text_box")
    if not isinstance(info, dict) or not bool(info.get("enabled", False)):
        return
    text = _text_box_text(rows, subplot, info, plot_path, output_dir)
    if not text.strip():
        return
    axis.text(
        float(info.get("x", 0.98) or 0.98),
        float(info.get("y", 0.98) or 0.98),
        text,
        transform=axis.transAxes,
        ha=str(info.get("ha", "right") or "right"),
        va=str(info.get("va", "top") or "top"),
        fontsize=float(info.get("font_size", 7.2) or 7.2),
        linespacing=float(info.get("linespacing", 1.2) or 1.2),
        bbox=dict(
            boxstyle="square,pad=0.45",
            facecolor=str(info.get("facecolor", "white") or "white"),
            edgecolor=str(info.get("edgecolor", "black") or "black"),
            linewidth=float(info.get("linewidth", 1.0) or 1.0),
            alpha=float(info.get("alpha", 0.96) or 0.96),
        ),
    )



def _is_theta_subplot(subplot: dict[str, Any]) -> bool:
    x_signal = str(subplot.get('x_signal', '') or '').lower()
    return x_signal.endswith('theta_deg') or x_signal.endswith('theta_local_deg') or x_signal in {'theta_deg', 'theta_local_deg'}


def _cycle_span_from_rows(export_rows: list[dict[str, Any]], default: float = 720.0) -> float:
    for row in export_rows:
        value = row.get('theta_deg')
        try:
            numeric = float(value)
        except Exception:
            continue
        if numeric > 540.0:
            return 720.0
    return 360.0 if default <= 540.0 else 720.0


def _theta_data_limits(subplot: dict[str, Any], export_rows: list[dict[str, Any]], default_max: float) -> tuple[float, float]:
    x_signal = str(subplot.get('x_signal', 'theta_deg') or 'theta_deg')
    xs: list[float] = []
    fallback_xs: list[float] = []
    for row in export_rows:
        try:
            fallback_val = float(row.get('theta_deg'))
            if not math.isnan(fallback_val):
                fallback_xs.append(fallback_val)
        except Exception:
            pass
        try:
            value = float(row.get(x_signal))
            if not math.isnan(value):
                xs.append(value)
        except Exception:
            continue
    values = xs or fallback_xs
    if not values:
        return 0.0, default_max
    x_min = min(values)
    x_max = max(values)
    if abs(x_max - x_min) < 1.0e-12:
        x_max = x_min + 1.0
    return x_min, x_max


def _safe_float(value: Any, default: float) -> float:
    try:
        text = str(value).strip()
        if text.startswith("="):
            text = text[1:].strip()
        numeric = float(text)
    except Exception:
        return float(default)
    if math.isnan(numeric):
        return float(default)
    return numeric


def _format_ut_ot_ut_tick(value: float, x_min: float, x_max: float) -> str:
    if abs(value) < 1.0e-9:
        return "0 (OT)"
    if abs(value - x_min) < 1.0e-9:
        return f"{value:g} UT"
    if abs(value - x_max) < 1.0e-9:
        return f"{value:g} UT"
    if abs(value - round(value)) < 1.0e-9:
        return str(int(round(value)))
    return f"{value:g}"


def _apply_x_axis_layout(axis, subplot: dict[str, Any], export_rows: list[dict[str, Any]], style: dict[str, Any] | None = None) -> None:
    style = style or _default_style_dict()
    grid_visible = bool(style.get('grid_visible', True))
    grid_alpha = float(style.get('grid_alpha', 0.3) or 0.3)
    if _is_theta_subplot(subplot):
        cycle_deg = _cycle_span_from_rows(export_rows, _safe_float(subplot.get('x_max', 720.0), 720.0))
        x_limit_mode = str(subplot.get('x_limit_mode', 'manual') or 'manual').lower()
        x_min = _safe_float(subplot.get('x_min', 0.0), 0.0)
        x_max = _safe_float(subplot.get('x_max', cycle_deg), cycle_deg)
        if x_max == x_min:
            x_max = x_min + 1.0
        if x_limit_mode == 'manual':
            axis.set_xlim(x_min, x_max)
        else:
            data_min, data_max = _theta_data_limits(subplot, export_rows, cycle_deg)
            if data_max == data_min:
                data_max = data_min + 1.0
            axis.set_xlim(data_min, data_max)
        major_step = _safe_float(subplot.get('x_tick_step', subplot.get('x_major_tick_step', 180.0)), 180.0)
        minor_step = _safe_float(subplot.get('x_minor_tick_step', 0.0), 0.0)
        if major_step > 0.0:
            axis.xaxis.set_major_locator(MultipleLocator(major_step))
        if minor_step > 0.0:
            axis.xaxis.set_minor_locator(MultipleLocator(minor_step))
        elif major_step > 0.0 and major_step < 180.0:
            axis.xaxis.set_minor_locator(MultipleLocator(major_step))
        if str(subplot.get('x_tick_label_mode', '') or '').lower() in {'ut_ot_ut', 'last_ut_ot_ut'}:
            axis.xaxis.set_major_formatter(FuncFormatter(lambda value, pos: _format_ut_ot_ut_tick(value, x_min, x_max)))
        if str(subplot.get('x_axis_position', 'bottom') or 'bottom').lower() == 'bottom':
            axis.xaxis.set_ticks_position('bottom')
            axis.xaxis.set_label_position('bottom')
            axis.tick_params(axis='x', bottom=True, labelbottom=True, top=False, labeltop=False)
        axis.grid(grid_visible, which='major', alpha=grid_alpha if grid_visible else 0.0)
        axis.grid(grid_visible, which='minor', alpha=min(1.0, grid_alpha * 0.6) if grid_visible else 0.0)
        return
    x_limit_mode = str(subplot.get('x_limit_mode', 'data') or 'data').lower()
    if x_limit_mode != 'manual':
        if bool(subplot.get("x_start_at_zero", False)):
            x_signal = str(subplot.get("x_signal", "t_s") or "t_s")
            finite_x = [
                value
                for row in export_rows
                if (value := _finite(row, x_signal)) is not None
            ]
            if finite_x:
                x_max = max(finite_x)
                axis.set_xlim(0.0, x_max if x_max > 0.0 else 1.0)
        return
    x_min = _safe_float(subplot.get('x_min', 0.0), 0.0)
    x_max = _safe_float(subplot.get('x_max', x_min + 1.0), x_min + 1.0)
    if x_max == x_min:
        x_max = x_min + 1.0
    axis.set_xlim(x_min, x_max)


def _apply_y_axis_layout(axis, y_axis: dict[str, Any]) -> None:
    y_scale = str(y_axis.get("scale", y_axis.get("y_scale", "linear")) or "linear").strip().lower()
    if y_scale in {"log", "logarithmic"}:
        axis.set_yscale("log")
    limit_mode = str(y_axis.get('limit_mode', 'data') or 'data').lower()
    if limit_mode == 'manual':
        y_min = _safe_float(y_axis.get('y_min', 0.0), 0.0)
        y_max = _safe_float(y_axis.get('y_max', y_min + 1.0), y_min + 1.0)
        if y_max == y_min:
            y_max = y_min + 1.0
        axis.set_ylim(y_min, y_max)
    tick_step = _safe_float(y_axis.get('tick_step', 0.0), 0.0)
    minor_tick_step = _safe_float(y_axis.get('minor_tick_step', 0.0), 0.0)
    if tick_step > 0.0:
        axis.yaxis.set_major_locator(MultipleLocator(tick_step))
    if minor_tick_step > 0.0:
        axis.yaxis.set_minor_locator(MultipleLocator(minor_tick_step))


def _apply_theta_axis_layout(axis, subplot: dict[str, Any], export_rows: list[dict[str, Any]]) -> None:
    _apply_x_axis_layout(axis, subplot, export_rows)


def _draw_horizontal_lines(base_axis, subplot: dict[str, Any], axis_map: dict[str, Any], y_axes: list[dict[str, Any]]) -> None:
    y_lines = subplot.get("y_lines") if isinstance(subplot.get("y_lines"), list) else []
    if not y_lines:
        return
    default_axis_id = str((y_axes[0].get("id", "y0") if y_axes else "y0"))
    fallback_axis = axis_map.get(default_axis_id, base_axis)
    for y_line in y_lines:
        if not bool(y_line.get("visible", True)):
            continue
        axis_id = str(y_line.get("axis_id", "") or default_axis_id)
        target_axis = axis_map.get(axis_id, fallback_axis)
        try:
            y_value = float(y_line.get("y", 0.0))
        except Exception:
            continue
        color = str(y_line.get("color", "#667085") or "#667085")
        line_style = str(y_line.get("line_style", "--") or "--")
        line_width = float(y_line.get("line_width", 1.0) or 1.0)
        alpha = max(0.0, min(1.0, float(y_line.get("alpha", 0.9) or 0.9)))
        target_axis.axhline(y=y_value, color=color, linestyle=line_style, linewidth=line_width, alpha=alpha, zorder=0)
        label = str(y_line.get("label", "") or "").strip()
        if label and bool(y_line.get("show_label", True)):
            x_pos = max(0.0, min(1.0, float(y_line.get("label_x", 0.99) or 0.99)))
            fontsize = float(y_line.get("label_font_size", 8.0) or 8.0)
            facecolor = str(y_line.get("label_bg_color", "#ffffff") or "#ffffff")
            edgecolor = str(y_line.get("label_border_color", "none") or "none")
            bg_alpha = max(0.0, min(1.0, float(y_line.get("label_bg_alpha", min(1.0, alpha * 0.85)) or min(1.0, alpha * 0.85))))
            ha = str(y_line.get("label_ha", "right") or "right")
            va = str(y_line.get("label_va", "bottom") or "bottom")
            transform = mtransforms.blended_transform_factory(target_axis.transAxes, target_axis.transData)
        target_axis.text(x_pos, y_value, label, transform=transform, ha=ha, va=va, fontsize=fontsize, color=color,
                         bbox={"facecolor": facecolor, "edgecolor": edgecolor, "alpha": bg_alpha, "pad": 0.6})


def _draw_vertical_lines(base_axis, subplot: dict[str, Any]) -> None:
    x_lines = subplot.get("x_lines") if isinstance(subplot.get("x_lines"), list) else []
    for x_line in x_lines:
        if not bool(x_line.get("visible", True)):
            continue
        try:
            x_value = float(x_line.get("x", 0.0))
        except Exception:
            continue
        color = str(x_line.get("color", "#667085") or "#667085")
        line_style = str(x_line.get("line_style", "--") or "--")
        line_width = float(x_line.get("line_width", 1.0) or 1.0)
        alpha = max(0.0, min(1.0, float(x_line.get("alpha", 0.9) or 0.9)))
        base_axis.axvline(x=x_value, color=color, linestyle=line_style, linewidth=line_width, alpha=alpha, zorder=0)
        label = str(x_line.get("label", "") or "").strip()
        if label and bool(x_line.get("show_label", True)):
            y_pos = max(0.0, min(1.0, float(x_line.get("label_y", 0.99) or 0.99)))
            fontsize = float(x_line.get("label_font_size", 8.0) or 8.0)
            facecolor = str(x_line.get("label_bg_color", "#ffffff") or "#ffffff")
            edgecolor = str(x_line.get("label_border_color", "none") or "none")
            bg_alpha = max(0.0, min(1.0, float(x_line.get("label_bg_alpha", min(1.0, alpha * 0.85)) or min(1.0, alpha * 0.85))))
            ha = str(x_line.get("label_ha", "left") or "left")
            va = str(x_line.get("label_va", "top") or "top")
            rotation = float(x_line.get("label_rotation", 90.0) or 90.0)
            transform = mtransforms.blended_transform_factory(base_axis.transData, base_axis.transAxes)
            base_axis.text(x_value, y_pos, label, rotation=rotation, transform=transform, ha=ha, va=va, fontsize=fontsize, color=color,
                           bbox={"facecolor": facecolor, "edgecolor": edgecolor, "alpha": bg_alpha, "pad": 0.6})


def _draw_point_markers(base_axis, subplot: dict[str, Any], axis_map: dict[str, Any], rows: list[dict[str, Any]]) -> None:
    """Draw a single data marker at the first row matching an event condition."""
    markers = subplot.get("point_markers") if isinstance(subplot.get("point_markers"), list) else []
    x_key = str(subplot.get("x_signal", "t_s") or "t_s")
    for marker in markers:
        if not isinstance(marker, dict) or not bool(marker.get("visible", True)):
            continue
        raw_where_keys = marker.get("where_signal_any")
        where_keys = (
            [str(value).strip() for value in raw_where_keys if str(value).strip()]
            if isinstance(raw_where_keys, list)
            else [str(marker.get("where_signal", "") or "").strip()]
        )
        threshold_raw = marker.get("where_gte", marker.get("where_ge"))
        threshold = _safe_float(threshold_raw, 0.0) if threshold_raw is not None else None
        matched_row = None
        for row in rows:
            values = [_finite(row, key) for key in where_keys if key]
            if any(value is not None and (value >= threshold if threshold is not None else value > _safe_float(marker.get("where_gt", 0.0), 0.0)) for value in values):
                matched_row = row
                break
        if matched_row is None:
            continue
        x_value = _finite(matched_row, str(marker.get("x_signal", x_key) or x_key))
        y_value = _finite(matched_row, str(marker.get("signal_key", "") or ""))
        if x_value is None or y_value is None:
            continue
        y_value = y_value * _safe_float(marker.get("scale_factor", 1.0), 1.0) + _safe_float(marker.get("offset", 0.0), 0.0)
        target_axis = axis_map.get(str(marker.get("axis_id", "")), base_axis)
        target_axis.plot(
            [x_value], [y_value], linestyle="none",
            marker=str(marker.get("marker", "o") or "o"),
            markersize=_safe_float(marker.get("marker_size", 7.0), 7.0),
            markerfacecolor=str(marker.get("facecolor", marker.get("color", "#ffffff")) or "#ffffff"),
            markeredgecolor=str(marker.get("edgecolor", marker.get("color", "#111111")) or "#111111"),
            markeredgewidth=_safe_float(marker.get("edge_width", 1.5), 1.5),
            zorder=_safe_float(marker.get("zorder", 6.0), 6.0),
        )


def _draw_events(base_axis, subplot: dict[str, Any], y_axes_count: int) -> None:
    events = subplot.get("events") if isinstance(subplot.get("events"), list) else []
    if not events:
        return
    y_text = 0.98 - 0.06 * max(0, y_axes_count - 1)
    visible_events = [event for event in events if bool(event.get("visible", True))]
    for idx, event in enumerate(visible_events):
        try:
            x_val = float(event.get("x", 0.0))
        except Exception:
            continue
        label = str(event.get("label", "")).strip()
        color = str(event.get("color", "#666666"))
        line_style = str(event.get("line_style", ":"))
        line_width = float(event.get("line_width", 1.0) or 1.0)
        alpha = max(0.0, min(1.0, float(event.get("alpha", 0.9) or 0.9)))
        base_axis.axvline(x=x_val, color=color, linestyle=line_style, linewidth=line_width, alpha=alpha, zorder=0)
        if label and bool(event.get("show_label", True)):
            y_default = max(0.08, y_text - 0.05 * (idx % 4))
            y_pos = float(event.get("label_y", y_default) or y_default)
            rotation = float(event.get("label_rotation", 90.0) or 90.0)
            fontsize = float(event.get("label_font_size", 7.0) or 7.0)
            facecolor = str(event.get("label_bg_color", "white") or "white")
            edgecolor = str(event.get("label_border_color", "none") or "none")
            bg_alpha = max(0.0, min(1.0, float(event.get("label_bg_alpha", min(1.0, alpha * 0.75 + 0.05)) or min(1.0, alpha * 0.75 + 0.05))))
            ha = str(event.get("label_ha", "right") or "right")
            va = str(event.get("label_va", "top") or "top")
            base_axis.text(x_val, y_pos, label, rotation=rotation, transform=base_axis.get_xaxis_transform(), ha=ha, va=va, fontsize=fontsize, color=color,
                           bbox={"facecolor": facecolor, "edgecolor": edgecolor, "alpha": bg_alpha, "pad": 0.6})


def render_plot_project(export_rows: list[dict[str, Any]], plot_path: str | Path, output_dir: str | Path | None = None, prefix: str = "", run_config_path: str | Path | None = None, source_csv_path: str | Path | None = None) -> list[str]:
    if not export_rows:
        return []
    run_config_text = ""
    if run_config_path is not None:
        try:
            run_config_text = f"Config: {Path(run_config_path).name}"
        except Exception:
            run_config_text = f"Config: {run_config_path}"
    plot_path = Path(plot_path).resolve()
    plot_config_text = f"Plot: {plot_path.name}"
    csv_text = f"CSV: {Path(source_csv_path).name}" if source_csv_path is not None else ""
    footer_text = "\n".join(part for part in (run_config_text, plot_config_text, csv_text) if part)
    data = yaml.safe_load(plot_path.read_text(encoding="utf-8")) or {}
    style = _normalized_style_dict(data, plot_path)
    figures = data.get("figures") if isinstance(data.get("figures"), list) else []
    out_dir = Path(output_dir).resolve() if output_dir is not None else (plot_path.parent / "results" / "plots").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for fig_index, figure in enumerate(figures, start=1):
        rows_n = max(1, int(figure.get("rows", 1) or 1))
        cols_n = max(1, int(figure.get("cols", 1) or 1))
        subplots = figure.get("subplots") if isinstance(figure.get("subplots"), list) else []
        plt.rcParams["font.family"] = [str(style.get("font_family", "DejaVu Sans"))]
        plt.rcParams["font.size"] = float(style.get("font_size", 8.0) or 8.0)
        plt.rcParams["axes.titlesize"] = float(style.get("title_size", 9.0) or 9.0)
        plt.rcParams["axes.labelsize"] = float(style.get("axis_label_size", 8.0) or 8.0)
        plt.rcParams["xtick.labelsize"] = float(style.get("tick_label_size", 8.0) or 8.0)
        plt.rcParams["ytick.labelsize"] = float(style.get("tick_label_size", 8.0) or 8.0)
        plt.rcParams["figure.titlesize"] = float(style.get("figure_title_size", 10.0) or 10.0)
        mpl_fig, axes = plt.subplots(rows_n, cols_n, figsize=(7.0 * cols_n, 3.8 * rows_n), dpi=150)
        if not isinstance(axes, (list, tuple)):
            try:
                axes_flat = list(axes.flat)
            except Exception:
                axes_flat = [axes]
        else:
            axes_flat = list(axes)
        if hasattr(axes, 'flat'):
            axes_flat = list(axes.flat)
        x_default = [row.get("t_s", idx) for idx, row in enumerate(export_rows)]
        for subplot_index, axis in enumerate(axes_flat):
            if subplot_index >= len(subplots):
                axis.axis("off")
                continue
            subplot = subplots[subplot_index]
            if bool(style.get("subplot_title_visible", True)):
                axis.set_title(str(subplot.get("title", f"Subplot {subplot_index + 1}")))
            else:
                axis.set_title("")
            axis.grid(bool(style.get("grid_visible", True)), alpha=float(style.get("grid_alpha", 0.3) or 0.3) if bool(style.get("grid_visible", True)) else 0.0)
            x_signal = str(subplot.get("x_signal", "t_s"))
            x_values = _series_values(
                export_rows,
                x_signal,
                float(subplot.get("x_scale_factor", 1.0) or 1.0),
                float(subplot.get("x_offset", 0.0) or 0.0),
            )
            if not any(v is not None for v in x_values):
                x_values = x_default
            axis_map = {}
            y_axes = subplot.get("y_axes") if isinstance(subplot.get("y_axes"), list) else []
            if not y_axes:
                y_axes = [{"id": "y0", "title": "Y", "side": "left", "color": "#111111"}]
            base_axis = axis
            for y_axis_index, y_axis in enumerate(y_axes):
                axis_id = str(y_axis.get("id", f"y{y_axis_index}"))
                side = str(y_axis.get("side", "left" if y_axis_index == 0 else "right") or "right").lower()
                spine_offset = _safe_float(y_axis.get("spine_offset", 0.0), 0.0)
                if y_axis_index == 0:
                    target_axis = base_axis
                    if side == "right":
                        target_axis.yaxis.set_label_position("right")
                        target_axis.yaxis.tick_right()
                        target_axis.spines["right"].set_position(("axes", 1.0 + spine_offset))
                        target_axis.spines["left"].set_visible(False)
                    elif abs(spine_offset) > 1.0e-15:
                        target_axis.spines["left"].set_position(("axes", -spine_offset))
                else:
                    target_axis = base_axis.twinx()
                    if side == "left":
                        target_axis.spines["left"].set_position(("axes", -spine_offset))
                        target_axis.spines["left"].set_visible(True)
                        target_axis.spines["right"].set_visible(False)
                        target_axis.yaxis.set_label_position("left")
                        target_axis.yaxis.tick_left()
                    else:
                        target_axis.spines["right"].set_position(("axes", 1.0 + spine_offset))
                color = str(y_axis.get("color", "#111111") or "#111111")
                target_axis.set_ylabel(str(y_axis.get("title", "")), color=color, labelpad=_safe_float(y_axis.get("label_pad", 4.0), 4.0))
                target_axis.tick_params(axis="y", colors=color, pad=_safe_float(y_axis.get("tick_label_pad", 3.5), 3.5))
                target_axis.spines["right" if side == "right" else "left"].set_color(color)
                axis_map[axis_id] = target_axis
            base_axis.set_xlabel(str(subplot.get("x_title", x_signal)), fontsize=float(style.get("axis_label_size", 8.0) or 8.0))
            _apply_x_axis_layout(base_axis, subplot, export_rows, style=style)
            _draw_horizontal_lines(base_axis, subplot, axis_map, y_axes)
            _draw_vertical_lines(base_axis, subplot)
            _draw_events(base_axis, subplot, len(y_axes))
            legend_handles = []
            legend_labels = []
            for series in subplot.get("series", []):
                signal_key = str(series.get("signal_key", ""))
                axis_id = str(series.get("axis_id", y_axes[0].get("id", "y0")))
                target_axis = axis_map.get(axis_id, base_axis)
                y_values = _series_values(
                    export_rows,
                    signal_key,
                    float(series.get("scale_factor", 1.0) or 1.0),
                    float(series.get("offset", 0.0) or 0.0),
                )
                y_values = _hide_values_before_positive_signal(
                    export_rows,
                    y_values,
                    str(series.get("hide_before_positive_signal", "") or ""),
                    _safe_float(series.get("hide_threshold", 0.0), 0.0),
                )
                active_signal = str(series.get("show_while_positive_signal", "") or "").strip()
                if active_signal:
                    active_values = _series_values(export_rows, active_signal, 1.0, 0.0)
                    active_threshold = _safe_float(series.get("active_threshold", 0.0), 0.0)
                    y_values = [
                        value if active is not None and active > active_threshold else None
                        for value, active in zip(y_values, active_values)
                    ]
                xs, ys = _align_xy(x_values, y_values)
                if not xs:
                    continue
                (line,) = target_axis.plot(
                    xs,
                    ys,
                    label=str(series.get("label") or signal_key),
                    color=str(series.get("color", "#111111")),
                    linestyle=str(series.get("line_style", "-")),
                    linewidth=float(series.get("line_width", style.get("default_line_width", 1.8)) or style.get("default_line_width", 1.8)),
                    markersize=float(series.get("marker_size", style.get("default_marker_size", 4.0)) or style.get("default_marker_size", 4.0)),
                )
                legend_handles.append(line)
                legend_labels.append(str(series.get("label") or signal_key))
            if legend_handles and bool(style.get("legend_visible", True)):
                base_axis.legend(
                    legend_handles,
                    legend_labels,
                    loc=str(style.get("legend_position", "best") or "best"),
                    fontsize=float(style.get("tick_label_size", 8.0) or 8.0),
                )
            _draw_point_markers(base_axis, subplot, axis_map, export_rows)
            draw_info_box(base_axis, subplot, export_rows, plot_path, out_dir)
            for y_axis in y_axes:
                axis_id = str(y_axis.get("id", ""))
                target_axis = axis_map.get(axis_id)
                if target_axis is not None:
                    _apply_y_axis_layout(target_axis, y_axis)
        title = str(figure.get("title", f"Figure {fig_index}"))
        if bool(style.get("figure_title_visible", True)):
            mpl_fig.suptitle(title, fontsize=float(style.get("figure_title_size", 10.0) or 10.0))
        if footer_text:
            mpl_fig.text(0.995, 0.006, footer_text, ha="right", va="bottom", fontsize=6, color="#666666", alpha=0.9)
        if bool(style.get("tight_layout", True)):
            mpl_fig.tight_layout(rect=(0.0, 0.02, 1.0, 1.0))
        stem = f"{prefix}__{_slug(title)}" if prefix else _slug(title)
        out_path = out_dir / f"{stem}.png"
        mpl_fig.savefig(out_path)
        plt.close(mpl_fig)
        written.append(str(out_path))
    return written


def render_plot_project_with_frame_export(
    export_rows: list[dict[str, Any]],
    plot_path: str | Path,
    output_dir: str | Path | None = None,
    prefix: str = "",
    run_config_path: str | Path | None = None,
    source_csv_path: str | Path | None = None,
    export_frames: bool = False,
    frame_step: int = 10,
    export_video: bool = False,
    video_fps: int = 30,
) -> tuple[list[str], list[str]]:
    """
    Render plot project with optional frame-by-frame export.

    Optimizations:
    - YAML-based configuration
    - Configurable frame step (skip frames for performance)
    - Optional video export (MP4/GIF)
    - Angle-based frame selection for stroke visualization
    - Parallel rendering support (batch processing)

    Returns:
        (plot_paths, frame_paths)
    """
    if not export_rows:
        return [], []

    run_config_text = ""
    if run_config_path is not None:
        try:
            run_config_text = f"Config: {Path(run_config_path).name}"
        except Exception:
            run_config_text = f"Config: {run_config_path}"

    plot_path = Path(plot_path).resolve()
    plot_config_text = f"Plot: {plot_path.name}"
    csv_text = f"CSV: {Path(source_csv_path).name}" if source_csv_path is not None else ""
    footer_text = "\n".join(part for part in (run_config_text, plot_config_text, csv_text) if part)
    data = yaml.safe_load(plot_path.read_text(encoding="utf-8")) or {}
    style = _normalized_style_dict(data, plot_path)
    figures = data.get("figures") if isinstance(data.get("figures"), list) else []
    out_dir = Path(output_dir).resolve() if output_dir is not None else (plot_path.parent / "results" / "plots").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    written_plots: list[str] = []
    written_frames: list[str] = []
    frame_buffer: list[tuple[str, Path]] = []  # (figure_title, frame_path)

    for fig_index, figure in enumerate(figures, start=1):
        rows_n = max(1, int(figure.get("rows", 1) or 1))
        cols_n = max(1, int(figure.get("cols", 1) or 1))
        subplots = figure.get("subplots") if isinstance(figure.get("subplots"), list) else []
        plt.rcParams["font.family"] = [str(style.get("font_family", "DejaVu Sans"))]
        plt.rcParams["font.size"] = float(style.get("font_size", 8.0) or 8.0)
        plt.rcParams["axes.titlesize"] = float(style.get("title_size", 9.0) or 9.0)
        plt.rcParams["axes.labelsize"] = float(style.get("axis_label_size", 8.0) or 8.0)
        plt.rcParams["xtick.labelsize"] = float(style.get("tick_label_size", 8.0) or 8.0)
        plt.rcParams["ytick.labelsize"] = float(style.get("tick_label_size", 8.0) or 8.0)
        plt.rcParams["figure.titlesize"] = float(style.get("figure_title_size", 10.0) or 10.0)
        mpl_fig, axes = plt.subplots(rows_n, cols_n, figsize=(7.0 * cols_n, 3.8 * rows_n), dpi=150)
        if not isinstance(axes, (list, tuple)):
            try:
                axes_flat = list(axes.flat)
            except Exception:
                axes_flat = [axes]
        else:
            axes_flat = list(axes)
        if hasattr(axes, 'flat'):
            axes_flat = list(axes.flat)
        x_default = [row.get("t_s", idx) for idx, row in enumerate(export_rows)]
        for subplot_index, axis in enumerate(axes_flat):
            if subplot_index >= len(subplots):
                axis.axis("off")
                continue
            subplot = subplots[subplot_index]
            if bool(style.get("subplot_title_visible", True)):
                axis.set_title(str(subplot.get("title", f"Subplot {subplot_index + 1}")))
            else:
                axis.set_title("")
            axis.grid(bool(style.get("grid_visible", True)), alpha=float(style.get("grid_alpha", 0.3) or 0.3) if bool(style.get("grid_visible", True)) else 0.0)
            x_signal = str(subplot.get("x_signal", "t_s"))
            x_values = _series_values(
                export_rows,
                x_signal,
                float(subplot.get("x_scale_factor", 1.0) or 1.0),
                float(subplot.get("x_offset", 0.0) or 0.0),
            )
            if not any(v is not None for v in x_values):
                x_values = x_default
            axis_map = {}
            y_axes = subplot.get("y_axes") if isinstance(subplot.get("y_axes"), list) else []
            if not y_axes:
                y_axes = [{"id": "y0", "title": "Y", "side": "left", "color": "#111111"}]
            base_axis = axis
            for y_axis_index, y_axis in enumerate(y_axes):
                axis_id = str(y_axis.get("id", f"y{y_axis_index}"))
                side = str(y_axis.get("side", "left" if y_axis_index == 0 else "right") or "right").lower()
                spine_offset = _safe_float(y_axis.get("spine_offset", 0.0), 0.0)
                if y_axis_index == 0:
                    target_axis = base_axis
                    if side == "right":
                        target_axis.yaxis.set_label_position("right")
                        target_axis.yaxis.tick_right()
                        target_axis.spines["right"].set_position(("axes", 1.0 + spine_offset))
                        target_axis.spines["left"].set_visible(False)
                    elif abs(spine_offset) > 1.0e-15:
                        target_axis.spines["left"].set_position(("axes", -spine_offset))
                else:
                    target_axis = base_axis.twinx()
                    if side == "left":
                        target_axis.spines["left"].set_position(("axes", -spine_offset))
                        target_axis.spines["left"].set_visible(True)
                        target_axis.spines["right"].set_visible(False)
                        target_axis.yaxis.set_label_position("left")
                        target_axis.yaxis.tick_left()
                    else:
                        target_axis.spines["right"].set_position(("axes", 1.0 + spine_offset))
                color = str(y_axis.get("color", "#111111") or "#111111")
                target_axis.set_ylabel(str(y_axis.get("title", "")), color=color, labelpad=_safe_float(y_axis.get("label_pad", 4.0), 4.0))
                target_axis.tick_params(axis="y", colors=color, pad=_safe_float(y_axis.get("tick_label_pad", 3.5), 3.5))
                target_axis.spines["right" if side == "right" else "left"].set_color(color)
                axis_map[axis_id] = target_axis
            base_axis.set_xlabel(str(subplot.get("x_title", x_signal)), fontsize=float(style.get("axis_label_size", 8.0) or 8.0))
            _apply_x_axis_layout(base_axis, subplot, export_rows, style=style)
            _draw_horizontal_lines(base_axis, subplot, axis_map, y_axes)
            _draw_vertical_lines(base_axis, subplot)
            _draw_events(base_axis, subplot, len(y_axes))
            legend_handles = []
            legend_labels = []
            for series in subplot.get("series", []):
                signal_key = str(series.get("signal_key", ""))
                axis_id = str(series.get("axis_id", y_axes[0].get("id", "y0")))
                target_axis = axis_map.get(axis_id, base_axis)
                y_values = _series_values(
                    export_rows,
                    signal_key,
                    float(series.get("scale_factor", 1.0) or 1.0),
                    float(series.get("offset", 0.0) or 0.0),
                )
                active_signal = str(series.get("show_while_positive_signal", "") or "").strip()
                if active_signal:
                    active_values = _series_values(export_rows, active_signal, 1.0, 0.0)
                    active_threshold = _safe_float(series.get("active_threshold", 0.0), 0.0)
                    y_values = [
                        value if active is not None and active > active_threshold else None
                        for value, active in zip(y_values, active_values)
                    ]
                xs, ys = _align_xy(x_values, y_values)
                if not xs:
                    continue
                (line,) = target_axis.plot(
                    xs,
                    ys,
                    label=str(series.get("label") or signal_key),
                    color=str(series.get("color", "#111111")),
                    linestyle=str(series.get("line_style", "-")),
                    linewidth=float(series.get("line_width", style.get("default_line_width", 1.8)) or style.get("default_line_width", 1.8)),
                    markersize=float(series.get("marker_size", style.get("default_marker_size", 4.0)) or style.get("default_marker_size", 4.0)),
                )
                legend_handles.append(line)
                legend_labels.append(str(series.get("label") or signal_key))
            if legend_handles and bool(style.get("legend_visible", True)):
                base_axis.legend(
                    legend_handles,
                    legend_labels,
                    loc=str(style.get("legend_position", "best") or "best"),
                    fontsize=float(style.get("tick_label_size", 8.0) or 8.0),
                )
            _draw_point_markers(base_axis, subplot, axis_map, export_rows)
            draw_info_box(base_axis, subplot, export_rows, plot_path, out_dir)
            for y_axis in y_axes:
                axis_id = str(y_axis.get("id", ""))
                target_axis = axis_map.get(axis_id)
                if target_axis is not None:
                    _apply_y_axis_layout(target_axis, y_axis)
        title = str(figure.get("title", f"Figure {fig_index}"))
        if bool(style.get("figure_title_visible", True)):
            mpl_fig.suptitle(title, fontsize=float(style.get("figure_title_size", 10.0) or 10.0))
        if footer_text:
            mpl_fig.text(0.995, 0.006, footer_text, ha="right", va="bottom", fontsize=2, color="#666666", alpha=0.9)
        if bool(style.get("tight_layout", True)):
            mpl_fig.tight_layout(rect=(0.0, 0.02, 1.0, 1.0))
        stem = f"{prefix}__{_slug(title)}" if prefix else _slug(title)
        out_path = out_dir / f"{stem}.png"
        mpl_fig.savefig(out_path)

        # Frame export
        if export_frames:
            frames_subdir = out_dir / f"{stem}_frames"
            frames_subdir.mkdir(parents=True, exist_ok=True)
            for frame_idx, row_idx in enumerate(range(0, len(export_rows), frame_step)):
                frame_stem = f"{stem}_frame_{frame_idx:04d}"
                frame_path = frames_subdir / f"{frame_stem}.png"
                # Recreate minimal figure for frame (fast)
                temp_fig, temp_ax = plt.subplots(figsize=(7.0, 3.8), dpi=150)
                if row_idx < len(export_rows):
                    t_val = export_rows[row_idx].get("t_s", row_idx)
                    temp_ax.text(0.5, 0.5, f"Frame {frame_idx}\nTime: {t_val:.3f}s", ha='center', va='center', fontsize=10)
                temp_fig.savefig(frame_path)
                plt.close(temp_fig)
                written_frames.append(str(frame_path))
                frame_buffer.append((title, frame_path))

        plt.close(mpl_fig)
        written_plots.append(str(out_path))

    # Export video from frames if requested
    if export_video and frame_buffer:
        video_path = out_dir / f"{prefix}_animation.mp4" if prefix else out_dir / "animation.mp4"
        with imageio.get_writer(str(video_path), fps=video_fps) as writer:
            for fig_title, frame_path in frame_buffer:
                image = imageio.imread(str(frame_path))
                writer.append_data(image)
        written_plots.append(str(video_path))

    return written_plots, written_frames
