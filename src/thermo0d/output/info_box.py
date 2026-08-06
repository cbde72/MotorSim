from __future__ import annotations

import math
from pathlib import Path
from typing import Any


def _finite(row: dict[str, Any], key: str) -> float | None:
    try:
        value = float(row.get(key, float("nan")))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def _first_finite(row: dict[str, Any], keys: list[str]) -> float | None:
    for key in keys:
        value = _finite(row, key)
        if value is not None:
            return value
    return None


def _column(rows: list[dict[str, Any]], key: str) -> list[float]:
    return [value if (value := _finite(row, key)) is not None else float("nan") for row in rows]


def _trapz(xs: list[float], ys: list[float], *, absolute: bool = False) -> float | None:
    total = 0.0
    used = False
    for index in range(1, min(len(xs), len(ys))):
        x0, x1 = xs[index - 1], xs[index]
        y0, y1 = ys[index - 1], ys[index]
        if not all(math.isfinite(value) for value in (x0, x1, y0, y1)) or x1 < x0:
            continue
        if absolute:
            y0, y1 = abs(y0), abs(y1)
        total += 0.5 * (y0 + y1) * (x1 - x0)
        used = True
    return total if used else None


def _safe_float(value: Any, default: float) -> float:
    try:
        result = float(str(value).lstrip("=").strip())
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _format_value(value: float | None, unit: str, digits: int = 2) -> str:
    if value is None or not math.isfinite(value):
        return "n/a"
    if abs(value) >= 1000.0 or (0.0 < abs(value) < 0.01):
        return f"{value:.3g} {unit}".strip()
    return f"{value:.{digits}f} {unit}".strip()


def _metric_value(rows: list[dict[str, Any]], metric: dict[str, Any], subplot: dict[str, Any]) -> float | None:
    kind = str(metric.get("kind", "")).lower().strip()
    if kind == "imep":
        cylinder = str(metric.get("cylinder", "") or "").strip()
        p_key = str(metric.get("pressure_signal", "") or (f"{cylinder}_p_Pa" if cylinder else "")).strip()
        v_key = str(metric.get("volume_signal", "") or (f"{cylinder}_V_m3" if cylinder else "")).strip()
        p_values, v_values = _column(rows, p_key), _column(rows, v_key)
        work = _trapz(v_values, p_values)
        finite_v = [value for value in v_values if math.isfinite(value)]
        swept = max(finite_v) - min(finite_v) if finite_v else None
        value = work / swept / 1.0e5 if work is not None and swept and swept > 1.0e-18 else None
    else:
        key = str(metric.get("signal_key", "") or "").strip()
        if not key:
            return None
        mode = str(metric.get("mode", "last") or "last").lower().strip()
        if mode == "first_where":
            raw_keys = metric.get("where_signal_any")
            where_keys = [str(item).strip() for item in raw_keys] if isinstance(raw_keys, list) else [str(metric.get("where_signal", "") or "").strip()]
            threshold_raw = metric.get("where_gte", metric.get("where_ge"))
            threshold = _safe_float(threshold_raw, 0.0) if threshold_raw is not None else None
            value = None
            for row in rows:
                where_values = [_finite(row, key_name) for key_name in where_keys if key_name]
                matches = any(item is not None and (item >= threshold if threshold is not None else item > _safe_float(metric.get("where_gt", 0.0), 0.0)) for item in where_values)
                if matches:
                    value = _finite(row, key)
                    break
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
    if bool(metric.get("absolute", False)) and str(metric.get("mode", "")).lower() != "integral":
        value = abs(value)
    value = value * _safe_float(metric.get("scale_factor", 1.0), 1.0) + _safe_float(metric.get("offset", 0.0), 0.0)
    return value if math.isfinite(value) else None


def _format_metric(value: float | None, metric: dict[str, Any]) -> str:
    unit = str(metric.get("unit", "") or "").strip()
    digits = int(metric.get("digits", 2) if metric.get("digits") is not None else 2)
    if value is None or not math.isfinite(value):
        return "n/a"
    if bool(metric.get("fixed", False)):
        text = f"{value:.{max(0, digits)}f}"
    elif bool(metric.get("scientific", False)):
        text = f"{value:.{max(0, digits)}e}"
    elif abs(value) >= 1000.0 or (0.0 < abs(value) < 0.01):
        text = f"{value:.{max(1, digits)}g}"
    else:
        text = f"{value:.{max(0, digits)}f}"
    return f"{text} {unit}".strip()


def _readme_values(info: dict[str, Any], plot_path: Path, output_dir: Path) -> dict[str, tuple[str, str]]:
    configured = str(info.get("readme_path", "") or info.get("path", "") or "").strip()
    candidates: list[Path] = []
    if configured:
        raw = Path(configured)
        candidates.extend([raw if raw.is_absolute() else plot_path.parent / raw, raw if raw.is_absolute() else output_dir / raw])
    candidates.extend([output_dir / "README.md", output_dir.parent / "README.md", plot_path.parent / "README.md", Path.cwd() / "README.md"])
    for candidate in candidates:
        if not candidate.is_file():
            continue
        values: dict[str, tuple[str, str]] = {}
        for line in candidate.read_text(encoding="utf-8", errors="ignore").splitlines():
            text = line.strip()
            if not text.startswith("|") or text.count("|") < 3:
                continue
            cells = [cell.strip().strip("`") for cell in text.strip("|").split("|")]
            if len(cells) >= 3 and cells[0] and set(cells[0]) != {"-"} and cells[0].lower() not in {"kennwert", "metric", "signal", "name"}:
                values[cells[0]] = (cells[1], cells[2])
        if values:
            return values
    return {}


def _generic_text(rows: list[dict[str, Any]], subplot: dict[str, Any], info: dict[str, Any], plot_path: Path, output_dir: Path) -> str:
    lines: list[str] = []
    title = str(info.get("title", "") or "").strip()
    if title:
        lines.append(title)
    readme = _readme_values(info, plot_path, output_dir) if str(info.get("source", "")).lower().strip() == "readme" else None
    for metric in info.get("metrics", []) if isinstance(info.get("metrics"), list) else []:
        if not isinstance(metric, dict):
            continue
        key = str(metric.get("readme_key", "") or metric.get("key", "") or metric.get("signal_key", "") or "").strip()
        label = str(metric.get("label", "") or key or metric.get("kind", "") or "").strip()
        if not label:
            continue
        if readme is not None:
            value, unit = readme.get(key, ("n/a", str(metric.get("unit", "") or "")))
            rendered = f"{value} {metric.get('unit', unit)}".strip()
        else:
            rendered = _format_metric(_metric_value(rows, metric, subplot), metric)
        lines.append(f"{label}{metric.get('separator', ': ')}{rendered}")
    return "\n".join(lines)


def _combustion_start_row(rows: list[dict[str, Any]], cylinder: str) -> dict[str, Any] | None:
    keys = [f"{cylinder}_combustion_active_0to1", f"{cylinder}_combustion_fraction_0to1", f"{cylinder}_added_energy_W"]
    for row in rows:
        if any((value := _finite(row, key)) is not None and value > 1.0e-12 for key in keys):
            return row
    return rows[len(rows) // 2] if rows else None


def _pv_text(rows: list[dict[str, Any]], cylinder: str) -> str:
    t_s = _column(rows, "t_s")
    p_pa = _column(rows, f"{cylinder}_p_Pa")
    volume = _column(rows, f"{cylinder}_V_m3")
    added_energy = _trapz(t_s, _column(rows, f"{cylinder}_added_energy_W"))
    wall_heat = _trapz(t_s, _column(rows, f"{cylinder}_wall_heat_W"), absolute=True)
    piston_work = _trapz(volume, p_pa)
    finite_p = [value for value in p_pa if math.isfinite(value)]
    finite_v = [value for value in volume if math.isfinite(value)]
    finite_t = [value for value in t_s if math.isfinite(value)]
    duration = finite_t[-1] - finite_t[0] if len(finite_t) >= 2 and finite_t[-1] > finite_t[0] else None
    swept = max(finite_v) - min(finite_v) if finite_v else None
    soc = _combustion_start_row(rows, cylinder)
    soc_p = _first_finite(soc, [f"{cylinder}_p_Pa", f"{cylinder}_p_bar"]) if soc else None
    if soc_p is not None and soc and f"{cylinder}_p_Pa" in soc:
        soc_p *= 1.0e-5
    burned = _first_finite(soc, [f"{cylinder}_share_burned_0to1"]) if soc else None
    heat_pct = f" ({round(wall_heat / added_energy * 100):.0f}%)" if wall_heat is not None and added_energy and added_energy > 0.0 else ""
    work_pct = f" ({round(piston_work / added_energy * 100):.0f}%)" if piston_work is not None and added_energy and added_energy > 0.0 else ""
    return "\n".join(
        [
            f"Fuel Energy: {_format_value(added_energy, 'J')}",
            f"Wall Heat: {_format_value(wall_heat, 'J')}{heat_pct}",
            f"Work: {_format_value(piston_work, 'J')}{work_pct}",
            "",
            f"SOC theta: {_format_value(_first_finite(soc, ['theta_deg', f'{cylinder}_theta_deg']) if soc else None, 'deg')}",
            f"p SOC: {_format_value(soc_p, 'bar')}",
            f"T SOC: {_format_value(_first_finite(soc, [f'{cylinder}_T_K']) if soc else None, 'K')}",
            f"Lambda (SOC): {_format_value(_first_finite(soc, [f'{cylinder}_thermo_lambda', f'{cylinder}_lambda']) if soc else None, '-', 3)}",
            f"Frequency: {_format_value(1.0 / duration if duration and duration > 1.0e-15 else None, 'Hz')}",
            f"Ind. Power: {_format_value(piston_work / duration / 1000.0 if piston_work is not None and duration and duration > 1.0e-15 else None, 'kW')}",
            f"pmi: {_format_value(piston_work / swept / 1.0e5 if piston_work is not None and swept and swept > 1.0e-18 else None, 'bar')}",
            f"pmax: {_format_value(max(finite_p) * 1.0e-5 if finite_p else None, 'bar')}",
            f"RGF: {_format_value(100.0 * max(0.0, min(1.0, burned)) if burned is not None else None, '%', 1)}",
            f"CR. real: {_format_value(max(finite_v) / min(finite_v) if finite_v and min(finite_v) > 1.0e-18 else None, '-', 1)}",
        ]
    )


def selected_info_box(subplot: dict[str, Any]) -> dict[str, Any] | None:
    for name in ("text_box", "info_box"):
        info = subplot.get(name)
        if isinstance(info, dict) and bool(info.get("enabled", False)):
            return info
    return None


def build_info_box_text(rows: list[dict[str, Any]], subplot: dict[str, Any], plot_path: Path, output_dir: Path) -> str:
    info = selected_info_box(subplot)
    if info is None:
        return ""
    if str(info.get("kind", "") or "").strip().lower() == "last_ut_ot_ut_pv":
        return _pv_text(rows, str(info.get("cylinder", "cylinder_1") or "cylinder_1"))
    return _generic_text(rows, subplot, info, plot_path, output_dir)


def draw_info_box(axis: Any, subplot: dict[str, Any], rows: list[dict[str, Any]], plot_path: Path, output_dir: Path) -> str | None:
    info = selected_info_box(subplot)
    if info is None:
        return None
    text = build_info_box_text(rows, subplot, plot_path, output_dir)
    if not text.strip():
        return None
    axis.text(
        _safe_float(info.get("x", 0.98), 0.98),
        _safe_float(info.get("y", 0.98), 0.98),
        text,
        transform=axis.transAxes,
        ha=str(info.get("ha", "right") or "right"),
        va=str(info.get("va", "top") or "top"),
        fontsize=_safe_float(info.get("font_size", 7.2), 7.2),
        linespacing=_safe_float(info.get("linespacing", 1.2), 1.2),
        bbox={
            "boxstyle": "square,pad=0.45",
            "facecolor": str(info.get("facecolor", "white") or "white"),
            "edgecolor": str(info.get("edgecolor", "black") or "black"),
            "linewidth": _safe_float(info.get("linewidth", 1.0), 1.0),
            "alpha": _safe_float(info.get("alpha", 0.96), 0.96),
        },
    )
    return text


def required_info_box_signal_keys(subplot: dict[str, Any]) -> set[str]:
    info = selected_info_box(subplot)
    if info is None:
        return set()
    keys: set[str] = set()
    for metric in info.get("metrics", []) if isinstance(info.get("metrics"), list) else []:
        if not isinstance(metric, dict):
            continue
        for field in ("signal_key", "x_signal", "pressure_signal", "volume_signal", "where_signal"):
            value = str(metric.get(field, "") or "").strip()
            if value:
                keys.add(value)
        keys.update(str(value).strip() for value in metric.get("where_signal_any", []) if str(value).strip())
    if str(info.get("kind", "") or "").strip().lower() == "last_ut_ot_ut_pv":
        cylinder = str(info.get("cylinder", "cylinder_1") or "cylinder_1")
        keys.update(
            {
                "t_s",
                "theta_deg",
                f"{cylinder}_theta_deg",
                f"{cylinder}_p_Pa",
                f"{cylinder}_p_bar",
                f"{cylinder}_V_m3",
                f"{cylinder}_added_energy_W",
                f"{cylinder}_wall_heat_W",
                f"{cylinder}_T_K",
                f"{cylinder}_thermo_lambda",
                f"{cylinder}_lambda",
                f"{cylinder}_combustion_active_0to1",
                f"{cylinder}_combustion_fraction_0to1",
                f"{cylinder}_share_burned_0to1",
            }
        )
    return keys
