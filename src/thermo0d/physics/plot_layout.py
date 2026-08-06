from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import transforms as mtransforms
from matplotlib.ticker import MultipleLocator
import yaml

from thermo0d.config.constants import CombCol, ConnCol, ConnectionType, VolumeCol, VolumeType
from thermo0d.physics.kinematics import reference_zero_deg, wrap_angle_deg


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(text).strip()).strip("_").lower()
    return slug or "figure"


def _series_def(signal_key: str, label: str, axis_id: str, color: str, line_style: str = "-", scale_factor: float = 1.0) -> dict[str, Any]:
    return {
        "signal_key": signal_key,
        "label": label,
        "axis_id": axis_id,
        "color": color,
        "line_style": line_style,
        "scale_factor": scale_factor,
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
                {"id": "ax_x", "title": "Weg [mm]", "side": "left", "color": "#111111"},
                {"id": "ax_v", "title": "Geschwindigkeit [m/s]", "side": "right", "color": "#1f77b4"},
            ],
            "series": [
                _series_def("free_piston_x_m", "Kolbenweg", "ax_x", "#111111", "-", 1000.0),
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
        numeric = float(value)
    except Exception:
        return float(default)
    if math.isnan(numeric):
        return float(default)
    return numeric


def _apply_x_axis_layout(axis, subplot: dict[str, Any], export_rows: list[dict[str, Any]]) -> None:
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
        axis.xaxis.set_major_locator(MultipleLocator(180.0))
        axis.xaxis.set_minor_locator(MultipleLocator(60.0))
        axis.grid(True, which='major', alpha=0.35)
        axis.grid(True, which='minor', alpha=0.18)
        return
    x_limit_mode = str(subplot.get('x_limit_mode', 'data') or 'data').lower()
    if x_limit_mode != 'manual':
        return
    x_min = _safe_float(subplot.get('x_min', 0.0), 0.0)
    x_max = _safe_float(subplot.get('x_max', x_min + 1.0), x_min + 1.0)
    if x_max == x_min:
        x_max = x_min + 1.0
    axis.set_xlim(x_min, x_max)


def _apply_y_axis_layout(axis, y_axis: dict[str, Any]) -> None:
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
    figures = data.get("figures") if isinstance(data.get("figures"), list) else []
    out_dir = Path(output_dir).resolve() if output_dir is not None else (plot_path.parent / "results" / "plots").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for fig_index, figure in enumerate(figures, start=1):
        rows_n = max(1, int(figure.get("rows", 1) or 1))
        cols_n = max(1, int(figure.get("cols", 1) or 1))
        subplots = figure.get("subplots") if isinstance(figure.get("subplots"), list) else []
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
            axis.set_title(str(subplot.get("title", f"Subplot {subplot_index + 1}")))
            axis.grid(True, alpha=0.3)
            x_signal = str(subplot.get("x_signal", "t_s"))
            x_values = _series_values(export_rows, x_signal)
            if not any(v is not None for v in x_values):
                x_values = x_default
            axis_map = {}
            y_axes = subplot.get("y_axes") if isinstance(subplot.get("y_axes"), list) else []
            if not y_axes:
                y_axes = [{"id": "y0", "title": "Y", "side": "left", "color": "#111111"}]
            base_axis = axis
            for y_axis_index, y_axis in enumerate(y_axes):
                axis_id = str(y_axis.get("id", f"y{y_axis_index}"))
                if y_axis_index == 0:
                    target_axis = base_axis
                else:
                    target_axis = base_axis.twinx()
                    if y_axis_index > 1:
                        target_axis.spines["right"].set_position(("outward", 60 * (y_axis_index - 1)))
                target_axis.set_ylabel(str(y_axis.get("title", "")))
                axis_map[axis_id] = target_axis
            base_axis.set_xlabel(str(subplot.get("x_title", x_signal)))
            _apply_x_axis_layout(base_axis, subplot, export_rows)
            _draw_horizontal_lines(base_axis, subplot, axis_map, y_axes)
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
                xs, ys = _align_xy(x_values, y_values)
                if not xs:
                    continue
                (line,) = target_axis.plot(
                    xs,
                    ys,
                    label=str(series.get("label") or signal_key),
                    color=str(series.get("color", "#111111")),
                    linestyle=str(series.get("line_style", "-")),
                    linewidth=float(series.get("line_width", 1.8) or 1.8),
                )
                legend_handles.append(line)
                legend_labels.append(str(series.get("label") or signal_key))
            if legend_handles:
                base_axis.legend(legend_handles, legend_labels, loc="best", fontsize=8)
            for y_axis in y_axes:
                axis_id = str(y_axis.get("id", ""))
                target_axis = axis_map.get(axis_id)
                if target_axis is not None:
                    _apply_y_axis_layout(target_axis, y_axis)
        title = str(figure.get("title", f"Figure {fig_index}"))
        mpl_fig.suptitle(title)
        if footer_text:
            mpl_fig.text(0.995, 0.006, footer_text, ha="right", va="bottom", fontsize=6, color="#666666", alpha=0.9)
        mpl_fig.tight_layout(rect=(0.0, 0.02, 1.0, 1.0))
        stem = f"{prefix}__{_slug(title)}" if prefix else _slug(title)
        out_path = out_dir / f"{stem}.png"
        mpl_fig.savefig(out_path)
        plt.close(mpl_fig)
        written.append(str(out_path))
    return written
