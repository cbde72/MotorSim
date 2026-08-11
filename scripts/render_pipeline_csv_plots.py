from __future__ import annotations

import argparse
import csv
import math
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import transforms as mtransforms
from matplotlib.ticker import FuncFormatter, MultipleLocator
import yaml

from thermo0d.output.info_box import draw_info_box


DEFAULT_CSV = ROOT / "Projekte" / "variants" / "results" / "free_piston_GenSet_V25" / "csv" / "signals.csv"
DEFAULT_PLOT_CFG = ROOT / "Projekte" / "variants" / "plot_CFG"
DEFAULT_OUTDIR = ROOT / "Projekte" / "variants" / "results" / "free_piston_GenSet_V25" / "plots_pipeline"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Render plot_CFG YAML layouts from a pipeline csv/signals.csv file.")
    parser.add_argument("--csv", default=str(DEFAULT_CSV), help="Pipeline CSV, normally <result>/csv/signals.csv.")
    parser.add_argument(
        "--compare",
        nargs="+",
        metavar="LABEL=CSV",
        help="Mehrere Pipeline-CSVs gemeinsam zeichnen, z. B. V55=.../signals.csv V56=.../signals.csv.",
    )
    parser.add_argument(
        "--x-mode",
        choices=("raw", "relative"),
        default="raw",
        help="raw: originale x-Werte; relative: jede Kurve beginnt bei x=0 (nur im Vergleichsmodus).",
    )
    parser.add_argument("--plot-cfg", default=str(DEFAULT_PLOT_CFG), help="A plot YAML file or a directory with *.yaml layouts.")
    parser.add_argument("--outdir", default=str(DEFAULT_OUTDIR), help="Directory for rendered PNG files.")
    parser.add_argument("--prefix", default="pipeline", help="Filename prefix for rendered plots.")
    parser.add_argument("--run-config", default=None, help="Optional simulation config name shown in the plot footer.")
    return parser.parse_args(argv)


COMPARE_COLORS = (
    "#175cd3",
    "#f79009",
    "#027a48",
    "#b42318",
    "#7a5af8",
    "#0891b2",
    "#667085",
)
COMPARE_LINE_STYLES = ("-", "--", "-.", ":")


def parse_compare_sources(values: list[str]) -> list[tuple[str, Path]]:
    sources: list[tuple[str, Path]] = []
    labels: set[str] = set()
    for value in values:
        label, separator, path_text = str(value).partition("=")
        label = label.strip()
        path_text = path_text.strip()
        if not separator or not label or not path_text:
            raise SystemExit(f"[ERROR] Ungueltige Vergleichsquelle {value!r}; erwartet wird LABEL=CSV.")
        if label in labels:
            raise SystemExit(f"[ERROR] Vergleichslabel mehrfach vergeben: {label}")
        labels.add(label)
        sources.append((label, Path(path_text).resolve()))
    if len(sources) < 2:
        raise SystemExit("[ERROR] --compare benoetigt mindestens zwei Quellen.")
    return sources


def _parse_float(value: str) -> float | str:
    text = str(value).strip()
    if not text:
        return ""
    try:
        return float(text)
    except ValueError:
        return text


def read_pipeline_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle, delimiter=";")
        try:
            headers = [str(value).strip() for value in next(reader)]
        except StopIteration:
            return []
        rows: list[dict[str, Any]] = []
        for raw_index, values in enumerate(reader):
            if raw_index < 2:
                # Pipeline CSV writes units and signal-kind metadata rows after the header.
                continue
            row: dict[str, Any] = {}
            for key, value in zip(headers, values, strict=False):
                row[key] = _parse_float(value)
            rows.append(row)
    _add_virtual_unit_columns(rows)
    return rows


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", str(text).strip()).strip("_").lower()
    return slug or "figure"


def _add_scaled_column(rows: list[dict[str, Any]], source: str, target: str, scale: float) -> None:
    if not rows or target in rows[0] or source not in rows[0]:
        return
    for row in rows:
        value = row.get(source)
        try:
            row[target] = float(value) * float(scale)
        except Exception:
            row[target] = ""


def _add_alias_column(rows: list[dict[str, Any]], source: str, target: str) -> None:
    if not rows or target in rows[0] or source not in rows[0]:
        return
    for row in rows:
        row[target] = row.get(source, "")


def _add_virtual_unit_columns(rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    headers = list(rows[0].keys())
    for key in headers:
        if key.endswith("_p_Pa"):
            _add_scaled_column(rows, key, key[:-5] + "_p_bar", 1.0e-5)
        if key.endswith("_Pa") and key.endswith("_p_Pa"):
            _add_scaled_column(rows, key, key[:-3] + "_bar", 1.0e-5)
        if key.endswith("_m"):
            _add_scaled_column(rows, key, key[:-2] + "_mm", 1.0e3)
        if key.endswith("_m2"):
            _add_scaled_column(rows, key, key[:-3] + "_mm2", 1.0e6)
    _add_alias_column(rows, "free_piston_distance_from_tdc_m", "cylinder_1_piston_distance_from_tdc_m")
    _add_alias_column(rows, "free_piston_distance_from_tdc_m", "cylinder_2_piston_distance_from_tdc_m")
    _add_alias_column(rows, "free_piston_x_m", "cylinder_1_piston_x_m")
    _add_alias_column(rows, "free_piston_x_m", "cylinder_2_piston_x_m")
    _add_alias_column(rows, "free_piston_v_m_per_s", "cylinder_1_piston_v_m_per_s")
    _add_alias_column(rows, "free_piston_v_m_per_s", "cylinder_2_piston_v_m_per_s")


def iter_plot_paths(path: Path) -> list[Path]:
    if path.is_file():
        return [path.resolve()]
    return sorted(path.resolve().glob("*.yaml"))


def _series_values(rows: list[dict[str, Any]], key: str, scale: float = 1.0, offset: float = 0.0) -> list[float]:
    values: list[float] = []
    for row in rows:
        try:
            value = float(row.get(key))
            if math.isfinite(value):
                values.append(value * scale + offset)
            else:
                values.append(float("nan"))
        except Exception:
            values.append(float("nan"))
    return values


def _hide_values_before_positive_signal(rows: list[dict[str, Any]], values: list[float], signal_key: str, threshold: float = 0.0) -> list[float]:
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
        masked[idx] = float("nan")
    return masked


def _finite_xy(xs: list[float], ys: list[float]) -> tuple[list[float], list[float]]:
    out_x: list[float] = []
    out_y: list[float] = []
    for x, y in zip(xs, ys, strict=False):
        if math.isfinite(x) and math.isfinite(y):
            out_x.append(x)
            out_y.append(y)
    return out_x, out_y


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


def _style(data: dict[str, Any], plot_path: Path | None = None) -> dict[str, Any]:
    style = {
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
    if plot_path is not None:
        style.update(_style_sheet_data(data, plot_path))
    if isinstance(data.get("style"), dict):
        style.update(data["style"])
    return style


def _safe_float(value: Any, default: float) -> float:
    try:
        text = str(value).strip()
        if text.startswith("="):
            text = text[1:].strip()
        numeric = float(text)
    except Exception:
        return float(default)
    return float(default) if math.isnan(numeric) else numeric


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


def _is_theta_subplot(subplot: dict[str, Any]) -> bool:
    x_signal = str(subplot.get("x_signal", "") or "").lower()
    return x_signal.endswith("theta_deg") or x_signal.endswith("theta_local_deg") or x_signal in {"theta_deg", "theta_local_deg"}


def _theta_data_limits(subplot: dict[str, Any], rows: list[dict[str, Any]], default_max: float) -> tuple[float, float]:
    x_signal = str(subplot.get("x_signal", "theta_deg") or "theta_deg")
    values: list[float] = []
    fallback: list[float] = []
    for row in rows:
        for key, target in (("theta_deg", fallback), (x_signal, values)):
            try:
                numeric = float(row.get(key))
            except Exception:
                continue
            if math.isfinite(numeric):
                target.append(numeric)
    selected = values or fallback
    if not selected:
        return 0.0, default_max
    x_min = min(selected)
    x_max = max(selected)
    if abs(x_max - x_min) < 1.0e-12:
        x_max = x_min + 1.0
    return x_min, x_max


def _cycle_span_from_rows(rows: list[dict[str, Any]], default: float = 720.0) -> float:
    for row in rows:
        try:
            if float(row.get("theta_deg")) > 540.0:
                return 720.0
        except Exception:
            continue
    return 360.0 if default <= 540.0 else 720.0


def _apply_x_axis_layout(axis, subplot: dict[str, Any], rows: list[dict[str, Any]], style: dict[str, Any]) -> None:
    grid_visible = bool(style.get("grid_visible", True))
    grid_alpha = float(style.get("grid_alpha", 0.3) or 0.3)
    if _is_theta_subplot(subplot):
        cycle_deg = _cycle_span_from_rows(rows, _safe_float(subplot.get("x_max", 720.0), 720.0))
        x_limit_mode = str(subplot.get("x_limit_mode", "manual") or "manual").lower()
        x_min = _safe_float(subplot.get("x_min", 0.0), 0.0)
        x_max = _safe_float(subplot.get("x_max", cycle_deg), cycle_deg)
        if x_max == x_min:
            x_max = x_min + 1.0
        if x_limit_mode == "manual":
            axis.set_xlim(x_min, x_max)
        else:
            axis.set_xlim(*_theta_data_limits(subplot, rows, cycle_deg))
        major_step = _safe_float(subplot.get("x_tick_step", subplot.get("x_major_tick_step", 180.0)), 180.0)
        minor_step = _safe_float(subplot.get("x_minor_tick_step", 0.0), 0.0)
        if major_step > 0.0:
            axis.xaxis.set_major_locator(MultipleLocator(major_step))
        if minor_step > 0.0:
            axis.xaxis.set_minor_locator(MultipleLocator(minor_step))
        elif major_step > 0.0 and major_step < 180.0:
            axis.xaxis.set_minor_locator(MultipleLocator(major_step))
        if str(subplot.get("x_tick_label_mode", "") or "").lower() in {"ut_ot_ut", "last_ut_ot_ut"}:
            axis.xaxis.set_major_formatter(FuncFormatter(lambda value, pos: _format_ut_ot_ut_tick(value, x_min, x_max)))
        if str(subplot.get("x_axis_position", "bottom") or "bottom").lower() == "bottom":
            axis.xaxis.set_ticks_position("bottom")
            axis.xaxis.set_label_position("bottom")
            axis.tick_params(axis="x", bottom=True, labelbottom=True, top=False, labeltop=False)
        axis.grid(grid_visible, which="major", alpha=grid_alpha if grid_visible else 0.0)
        axis.grid(grid_visible, which="minor", alpha=min(1.0, grid_alpha * 0.6) if grid_visible else 0.0)
        return
    x_limit_mode = str(subplot.get("x_limit_mode", "data") or "data").lower()
    if x_limit_mode == "manual":
        x_min = _safe_float(subplot.get("x_min", 0.0), 0.0)
        x_max = _safe_float(subplot.get("x_max", x_min + 1.0), x_min + 1.0)
        axis.set_xlim(x_min, x_max if x_max != x_min else x_min + 1.0)


def _apply_y_axis_layout(axis, y_axis: dict[str, Any]) -> None:
    limit_mode = str(y_axis.get("limit_mode", "data") or "data").lower()
    if limit_mode == "manual":
        y_min = _safe_float(y_axis.get("y_min", 0.0), 0.0)
        y_max = _safe_float(y_axis.get("y_max", y_min + 1.0), y_min + 1.0)
        axis.set_ylim(y_min, y_max if y_max != y_min else y_min + 1.0)
    tick_step = _safe_float(y_axis.get("tick_step", 0.0), 0.0)
    minor_tick_step = _safe_float(y_axis.get("minor_tick_step", 0.0), 0.0)
    if tick_step > 0.0:
        axis.yaxis.set_major_locator(MultipleLocator(tick_step))
    if minor_tick_step > 0.0:
        axis.yaxis.set_minor_locator(MultipleLocator(minor_tick_step))


def _axis_for(base_axis, axes_by_id: dict[str, Any], axis_specs: list[dict[str, Any]], axis_id: str):
    if axis_id in axes_by_id:
        return axes_by_id[axis_id]
    spec = next((item for item in axis_specs if str(item.get("id", "")) == axis_id), {})
    axis = base_axis if not axes_by_id else base_axis.twinx()
    side = str(spec.get("side", "left" if not axes_by_id else "right") or "right").lower()
    spine_offset = _safe_float(spec.get("spine_offset", 0.0), 0.0)
    if side == "right":
        axis.spines["right"].set_position(("axes", 1.0 + spine_offset))
        axis.yaxis.set_label_position("right")
        axis.yaxis.tick_right()
        if axis is base_axis:
            axis.spines["left"].set_visible(False)
    else:
        axis.spines["left"].set_position(("axes", -spine_offset))
        axis.yaxis.set_label_position("left")
        axis.yaxis.tick_left()
        if axis is not base_axis:
            axis.spines["left"].set_visible(True)
            axis.spines["right"].set_visible(False)
    title = str(spec.get("title", "") or "")
    color = str(spec.get("color", "#111111") or "#111111")
    axis.set_ylabel(title, color=color, labelpad=_safe_float(spec.get("label_pad", 4.0), 4.0))
    axis.tick_params(axis="y", colors=color, pad=_safe_float(spec.get("tick_label_pad", 3.5), 3.5))
    axis.spines["right" if side == "right" else "left"].set_color(color)
    axes_by_id[axis_id] = axis
    return axis


def _draw_annotations(base_axis, subplot: dict[str, Any], rows: list[dict[str, Any]], x_values: list[float]) -> None:
    for line in subplot.get("y_lines", []) or []:
        if not isinstance(line, dict):
            continue
        if not bool(line.get("visible", True)):
            continue
        try:
            y = float(line.get("y"))
        except Exception:
            continue
        color = str(line.get("color", "#666666") or "#666666")
        line_style = str(line.get("line_style", "--") or "--")
        line_width = float(line.get("line_width", 1.0) or 1.0)
        alpha = float(line.get("alpha", 0.9) or 0.9)
        base_axis.axhline(
            y,
            color=color,
            linestyle=line_style,
            linewidth=line_width,
            alpha=alpha,
            zorder=0,
        )
        label = str(line.get("label", "") or "").strip()
        if label and bool(line.get("show_label", True)):
            x_pos = max(0.0, min(1.0, float(line.get("label_x", 0.99) or 0.99)))
            fontsize = float(line.get("label_font_size", 8.0) or 8.0)
            facecolor = str(line.get("label_bg_color", "#ffffff") or "#ffffff")
            edgecolor = str(line.get("label_border_color", "none") or "none")
            bg_alpha = max(0.0, min(1.0, float(line.get("label_bg_alpha", min(1.0, alpha * 0.85)) or min(1.0, alpha * 0.85))))
            ha = str(line.get("label_ha", "right") or "right")
            va = str(line.get("label_va", "bottom") or "bottom")
            transform = mtransforms.blended_transform_factory(base_axis.transAxes, base_axis.transData)
            base_axis.text(x_pos, y, label, transform=transform, ha=ha, va=va, fontsize=fontsize, color=color,
                           bbox={"facecolor": facecolor, "edgecolor": edgecolor, "alpha": bg_alpha, "pad": 0.6})
    for span in subplot.get("x_spans", []) or []:
        if not isinstance(span, dict):
            continue
        key = str(span.get("signal_key", "") or "")
        if not rows or key not in rows[0]:
            continue
        try:
            threshold = float(span.get("threshold", 0.0) or 0.0)
        except Exception:
            threshold = 0.0
        active_when = str(span.get("active_when", "above") or "above")
        values = _series_values(rows, key)
        active = [(value >= threshold if active_when == "above" else value <= threshold) for value in values]
        start: float | None = None
        for x, is_active in zip(x_values, active, strict=False):
            if not math.isfinite(x):
                continue
            if is_active and start is None:
                start = x
            elif not is_active and start is not None:
                base_axis.axvspan(start, x, color=str(span.get("color", "#cccccc")), alpha=float(span.get("alpha", 0.15) or 0.15))
                start = None
        finite_x = [x for x in x_values if math.isfinite(x)]
        if start is not None and finite_x:
            base_axis.axvspan(start, finite_x[-1], color=str(span.get("color", "#cccccc")), alpha=float(span.get("alpha", 0.15) or 0.15))

    events = subplot.get("events") if isinstance(subplot.get("events"), list) else []
    visible_events = [event for event in events if isinstance(event, dict) and bool(event.get("visible", True))]
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
            y_default = max(0.08, 0.98 - 0.05 * (idx % 4))
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


def _finite(row: dict[str, Any], key: str) -> float | None:
    try:
        value = float(row.get(key))
    except Exception:
        return None
    return value if math.isfinite(value) else None


def render_plot_project_from_rows(rows: list[dict[str, Any]], plot_path: Path, output_dir: Path, prefix: str, run_config_path: Path | None = None, source_csv_path: Path | None = None) -> list[str]:
    data = yaml.safe_load(plot_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    style = _style(data, plot_path)
    run_config_text = f"Config: {run_config_path.name}" if run_config_path is not None else ""
    plot_config_text = f"Plot: {plot_path.name}"
    csv_text = f"CSV: {source_csv_path.name}" if source_csv_path is not None else ""
    footer_text = "\n".join(part for part in (run_config_text, plot_config_text, csv_text) if part)
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[str] = []
    figures = data.get("figures") if isinstance(data.get("figures"), list) else []
    for fig_index, fig_def in enumerate(figures, start=1):
        if not isinstance(fig_def, dict):
            continue
        subplots = fig_def.get("subplots") if isinstance(fig_def.get("subplots"), list) else []
        if not subplots:
            continue
        nrows = max(int(fig_def.get("rows", 1) or 1), 1)
        ncols = max(int(fig_def.get("cols", 1) or 1), 1)
        plt.rcParams["font.family"] = [str(style.get("font_family", "DejaVu Sans"))]
        plt.rcParams["font.size"] = float(style.get("font_size", 8.0) or 8.0)
        plt.rcParams["axes.titlesize"] = float(style.get("title_size", 9.0) or 9.0)
        plt.rcParams["axes.labelsize"] = float(style.get("axis_label_size", 8.0) or 8.0)
        plt.rcParams["xtick.labelsize"] = float(style.get("tick_label_size", 8.0) or 8.0)
        plt.rcParams["ytick.labelsize"] = float(style.get("tick_label_size", 8.0) or 8.0)
        plt.rcParams["figure.titlesize"] = float(style.get("figure_title_size", 10.0) or 10.0)
        fig, axes = plt.subplots(nrows, ncols, figsize=(7.0 * ncols, 3.8 * nrows), dpi=150, squeeze=False)
        figure_has_data = False
        x_default = [row.get("t_s", idx) for idx, row in enumerate(rows)]
        for subplot_index, subplot in enumerate(subplots):
            if not isinstance(subplot, dict):
                continue
            row_idx = subplot_index // ncols
            col_idx = subplot_index % ncols
            if row_idx >= nrows:
                continue
            base_axis = axes[row_idx][col_idx]
            axis_specs = [item for item in (subplot.get("y_axes") or [{"id": "y0"}]) if isinstance(item, dict)]
            axes_by_id: dict[str, Any] = {}
            for axis_index, axis_spec in enumerate(axis_specs):
                axis_id = str(axis_spec.get("id", f"y{axis_index}") or f"y{axis_index}")
                _axis_for(base_axis, axes_by_id, axis_specs, axis_id)
            x_key = str(subplot.get("x_signal", "t_s") or "t_s")
            x_values = _series_values(
                rows,
                x_key,
                float(subplot.get("x_scale_factor", 1.0) or 1.0),
                float(subplot.get("x_offset", 0.0) or 0.0),
            )
            if not any(math.isfinite(value) for value in x_values):
                x_values = [float(value) for value in x_default]
            _draw_annotations(base_axis, subplot, rows, x_values)
            labels: list[tuple[Any, str]] = []
            for series in subplot.get("series", []) or []:
                if not isinstance(series, dict):
                    continue
                signal_key = str(series.get("signal_key", "") or "")
                if not signal_key or (rows and signal_key not in rows[0]):
                    continue
                axis_id = str(series.get("axis_id", axis_specs[0].get("id", "y0")) or "y0")
                axis = axes_by_id.get(axis_id) or base_axis
                y_values = _series_values(
                    rows,
                    signal_key,
                    float(series.get("scale_factor", 1.0) or 1.0),
                    float(series.get("offset", 0.0) or 0.0),
                )
                y_values = _hide_values_before_positive_signal(
                    rows,
                    y_values,
                    str(series.get("hide_before_positive_signal", "") or ""),
                    _safe_float(series.get("hide_threshold", 0.0), 0.0),
                )
                xs, ys = _finite_xy(x_values, y_values)
                if not xs:
                    continue
                line, = axis.plot(
                    xs,
                    ys,
                    label=str(series.get("label") or signal_key),
                    color=str(series.get("color", "#111111") or "#111111"),
                    linestyle=str(series.get("line_style", "-") or "-"),
                    linewidth=float(series.get("line_width", style.get("default_line_width", 1.8)) or style.get("default_line_width", 1.8)),
                    markersize=float(series.get("marker_size", style.get("default_marker_size", 4.0)) or style.get("default_marker_size", 4.0)),
                )
                labels.append((line, str(series.get("label") or signal_key)))
                figure_has_data = True
            if bool(style.get("subplot_title_visible", True)):
                base_axis.set_title(str(subplot.get("title", "") or ""), fontsize=float(style.get("title_size", 9.0) or 9.0))
            else:
                base_axis.set_title("")
            base_axis.set_xlabel(str(subplot.get("x_title", x_key) or x_key), fontsize=float(style.get("axis_label_size", 8.0) or 8.0))
            if bool(style.get("grid_visible", True)):
                base_axis.grid(True, alpha=float(style.get("grid_alpha", 0.3) or 0.3))
            if labels and bool(style.get("legend_visible", True)):
                base_axis.legend([line for line, _ in labels], [label for _, label in labels], loc=str(style.get("legend_position", "best") or "best"), fontsize=float(style.get("tick_label_size", 8.0) or 8.0))
            draw_info_box(base_axis, subplot, rows, plot_path, output_dir)
            _apply_x_axis_layout(base_axis, subplot, rows, style)
            for axis_spec in axis_specs:
                axis_id = str(axis_spec.get("id", ""))
                target_axis = axes_by_id.get(axis_id)
                if target_axis is not None:
                    _apply_y_axis_layout(target_axis, axis_spec)
        for empty_index in range(len(subplots), nrows * ncols):
            axes[empty_index // ncols][empty_index % ncols].axis("off")
        title = str(fig_def.get("title", f"Figure {fig_index}") or f"Figure {fig_index}")
        if bool(style.get("figure_title_visible", True)):
            fig.suptitle(title, fontsize=float(style.get("figure_title_size", 10.0) or 10.0))
        if footer_text:
            fig.text(0.995, 0.006, footer_text, ha="right", va="bottom", fontsize=6, color="#666666", alpha=0.9)
        if bool(style.get("tight_layout", True)):
            fig.tight_layout(rect=(0.0, 0.02, 1.0, 1.0))
        if figure_has_data:
            out = output_dir / f"{prefix}__{_slug(title)}.png"
            fig.savefig(out)
            rendered.append(str(out))
        plt.close(fig)
    return rendered


def _relative_values(values: list[float]) -> list[float]:
    origin = next((value for value in values if math.isfinite(value)), 0.0)
    return [value - origin if math.isfinite(value) else value for value in values]


def render_comparison_plot(
    datasets: list[tuple[str, list[dict[str, Any]], Path]],
    plot_path: Path,
    output_dir: Path,
    prefix: str,
    x_mode: str = "raw",
) -> list[str]:
    data = yaml.safe_load(plot_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    style = _style(data, plot_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    rendered: list[str] = []
    figures = data.get("figures") if isinstance(data.get("figures"), list) else []
    for fig_index, fig_def in enumerate(figures, start=1):
        if not isinstance(fig_def, dict):
            continue
        subplots = fig_def.get("subplots") if isinstance(fig_def.get("subplots"), list) else []
        if not subplots:
            continue
        nrows = max(int(fig_def.get("rows", 1) or 1), 1)
        ncols = max(int(fig_def.get("cols", 1) or 1), 1)
        plt.rcParams["font.family"] = [str(style.get("font_family", "DejaVu Sans"))]
        plt.rcParams["font.size"] = float(style.get("font_size", 8.0) or 8.0)
        fig, axes = plt.subplots(nrows, ncols, figsize=(7.0 * ncols, 3.8 * nrows), dpi=150, squeeze=False)
        figure_has_data = False
        for subplot_index, subplot in enumerate(subplots):
            if not isinstance(subplot, dict):
                continue
            row_idx, col_idx = divmod(subplot_index, ncols)
            if row_idx >= nrows:
                continue
            base_axis = axes[row_idx][col_idx]
            axis_specs = [item for item in (subplot.get("y_axes") or [{"id": "y0"}]) if isinstance(item, dict)]
            axes_by_id: dict[str, Any] = {}
            for axis_index, axis_spec in enumerate(axis_specs):
                axis_id = str(axis_spec.get("id", f"y{axis_index}") or f"y{axis_index}")
                _axis_for(base_axis, axes_by_id, axis_specs, axis_id)
            labels: list[tuple[Any, str]] = []
            x_key = str(subplot.get("x_signal", "t_s") or "t_s")
            for dataset_index, (dataset_label, rows, _) in enumerate(datasets):
                x_values = _series_values(
                    rows,
                    x_key,
                    float(subplot.get("x_scale_factor", 1.0) or 1.0),
                    float(subplot.get("x_offset", 0.0) or 0.0),
                )
                if not any(math.isfinite(value) for value in x_values):
                    x_values = [float(index) for index in range(len(rows))]
                if x_mode == "relative":
                    x_values = _relative_values(x_values)
                for series_index, series in enumerate(subplot.get("series", []) or []):
                    if not isinstance(series, dict):
                        continue
                    signal_key = str(series.get("signal_key", "") or "")
                    if not signal_key or (rows and signal_key not in rows[0]):
                        continue
                    axis_id = str(series.get("axis_id", axis_specs[0].get("id", "y0")) or "y0")
                    axis = axes_by_id.get(axis_id) or base_axis
                    y_values = _series_values(rows, signal_key, float(series.get("scale_factor", 1.0) or 1.0), float(series.get("offset", 0.0) or 0.0))
                    y_values = _hide_values_before_positive_signal(rows, y_values, str(series.get("hide_before_positive_signal", "") or ""), _safe_float(series.get("hide_threshold", 0.0), 0.0))
                    xs, ys = _finite_xy(x_values, y_values)
                    if not xs:
                        continue
                    series_label = str(series.get("label") or signal_key)
                    legend_label = f"{dataset_label} – {series_label}"
                    line, = axis.plot(
                        xs,
                        ys,
                        label=legend_label,
                        color=COMPARE_COLORS[dataset_index % len(COMPARE_COLORS)],
                        linestyle=str(series.get("compare_line_style") or COMPARE_LINE_STYLES[series_index % len(COMPARE_LINE_STYLES)]),
                        linewidth=float(series.get("line_width", style.get("default_line_width", 1.8)) or style.get("default_line_width", 1.8)),
                        markersize=float(series.get("marker_size", style.get("default_marker_size", 4.0)) or style.get("default_marker_size", 4.0)),
                    )
                    labels.append((line, legend_label))
                    figure_has_data = True
            first_rows = datasets[0][1]
            if bool(style.get("subplot_title_visible", True)):
                base_axis.set_title(str(subplot.get("title", "") or ""), fontsize=float(style.get("title_size", 9.0) or 9.0))
            base_axis.set_xlabel(str(subplot.get("x_title", x_key) or x_key), fontsize=float(style.get("axis_label_size", 8.0) or 8.0))
            if bool(style.get("grid_visible", True)):
                base_axis.grid(True, alpha=float(style.get("grid_alpha", 0.3) or 0.3))
            if labels and bool(style.get("legend_visible", True)):
                base_axis.legend([line for line, _ in labels], [label for _, label in labels], loc=str(style.get("legend_position", "best") or "best"), fontsize=float(style.get("tick_label_size", 8.0) or 8.0))
            _apply_x_axis_layout(base_axis, subplot, first_rows, style)
            for axis_spec in axis_specs:
                target_axis = axes_by_id.get(str(axis_spec.get("id", "")))
                if target_axis is not None:
                    _apply_y_axis_layout(target_axis, axis_spec)
        for empty_index in range(len(subplots), nrows * ncols):
            axes[empty_index // ncols][empty_index % ncols].axis("off")
        title = str(fig_def.get("title", f"Figure {fig_index}") or f"Figure {fig_index}")
        if bool(style.get("figure_title_visible", True)):
            fig.suptitle(title, fontsize=float(style.get("figure_title_size", 10.0) or 10.0))
        sources_text = ", ".join(label for label, _, _ in datasets)
        fig.text(0.995, 0.006, f"Vergleich: {sources_text}\nPlot: {plot_path.name}", ha="right", va="bottom", fontsize=6, color="#666666", alpha=0.9)
        if bool(style.get("tight_layout", True)):
            fig.tight_layout(rect=(0.0, 0.02, 1.0, 1.0))
        if figure_has_data:
            out = output_dir / f"{prefix}__{fig_index:02d}__{_slug(title)}.png"
            fig.savefig(out)
            rendered.append(str(out))
        plt.close(fig)
    return rendered


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    plot_cfg_path = Path(args.plot_cfg).resolve()
    outdir = Path(args.outdir).resolve()
    if args.compare:
        sources = parse_compare_sources(args.compare)
        rendered = render_pipeline_csv_comparison(sources, plot_cfg_path, outdir, str(args.prefix), x_mode=args.x_mode)
        print(f"[plots] compare={', '.join(label for label, _ in sources)}")
        print(f"[plots] outdir={outdir}")
        print(f"[plots] rendered={len(rendered)}")
        for path in rendered:
            print(f"[plot] {path}")
        return 0
    csv_path = Path(args.csv).resolve()
    run_config_path = Path(args.run_config).resolve() if args.run_config else None
    rendered = render_pipeline_csv_plots(csv_path, plot_cfg_path, outdir, str(args.prefix), run_config_path=run_config_path)
    print(f"[plots] csv={csv_path}")
    print(f"[plots] outdir={outdir}")
    print(f"[plots] rendered={len(rendered)}")
    for path in rendered:
        print(f"[plot] {path}")
    return 0


def _clear_prefixed_pngs(outdir: Path, prefix: str) -> None:
    if not prefix or not outdir.exists():
        return
    for path in outdir.glob(f"{prefix}__*.png"):
        if path.is_file():
            try:
                path.unlink()
            except OSError:
                pass


def render_pipeline_csv_plots(csv_path: Path, plot_cfg_path: Path, outdir: Path, prefix: str = "pipeline", run_config_path: Path | None = None, clean: bool = True) -> list[str]:
    csv_path = Path(csv_path).resolve()
    plot_cfg_path = Path(plot_cfg_path).resolve()
    outdir = Path(outdir).resolve()
    rows = read_pipeline_csv(csv_path)
    if not rows:
        raise SystemExit(f"[ERROR] CSV enthaelt keine Datenzeilen: {csv_path}")
    plot_paths = iter_plot_paths(plot_cfg_path)
    if not plot_paths:
        raise SystemExit(f"[ERROR] Keine Plot-Konfigurationen gefunden: {plot_cfg_path}")
    if clean:
        _clear_prefixed_pngs(outdir, str(prefix).strip())
    rendered: list[str] = []
    for plot_path in plot_paths:
        file_prefix = "__".join(part for part in (str(prefix).strip(), plot_path.stem.replace("-", "_")) if part)
        rendered.extend(render_plot_project_from_rows(rows, plot_path, outdir, file_prefix, run_config_path=run_config_path, source_csv_path=csv_path))
    return rendered


def render_pipeline_csv_comparison(
    sources: list[tuple[str, Path]],
    plot_cfg_path: Path,
    outdir: Path,
    prefix: str = "comparison",
    x_mode: str = "raw",
    clean: bool = True,
) -> list[str]:
    plot_cfg_path = Path(plot_cfg_path).resolve()
    outdir = Path(outdir).resolve()
    datasets: list[tuple[str, list[dict[str, Any]], Path]] = []
    for label, source_path in sources:
        csv_path = Path(source_path).resolve()
        rows = read_pipeline_csv(csv_path)
        if not rows:
            raise SystemExit(f"[ERROR] CSV enthaelt keine Datenzeilen: {csv_path}")
        datasets.append((str(label), rows, csv_path))
    plot_paths = iter_plot_paths(plot_cfg_path)
    if not plot_paths:
        raise SystemExit(f"[ERROR] Keine Plot-Konfigurationen gefunden: {plot_cfg_path}")
    if clean:
        _clear_prefixed_pngs(outdir, str(prefix).strip())
    rendered: list[str] = []
    for plot_path in plot_paths:
        file_prefix = "__".join(part for part in (str(prefix).strip(), plot_path.stem.replace("-", "_")) if part)
        rendered.extend(render_comparison_plot(datasets, plot_path, outdir, file_prefix, x_mode=x_mode))
    return rendered


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
