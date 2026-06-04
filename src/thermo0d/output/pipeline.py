from __future__ import annotations

from dataclasses import dataclass, field
import csv
import hashlib
from pathlib import Path
from types import SimpleNamespace
from time import perf_counter
from typing import Any

import numpy as np
import yaml

from thermo0d.app.paths import PathManager
from thermo0d.model.free_piston.cycle_metrics import count_ut_ot_ut_cycles, find_last_ut_ot_ut_turning_points
from thermo0d.output.console import ConsoleArtifactReporter, ConsoleProgressReporter, ConsoleTimingReporter
from thermo0d.output.geometry_report import write_geometry_readme
from thermo0d.output.plot_layout import ensure_default_plot10_yaml, ensure_default_plot_yaml, render_plot_project
from thermo0d.output.reconstruction import SignalReconstructionService


SIGNAL_RAW = "raw"
SIGNAL_DERIVATIVE = "derivative"
SIGNAL_RECONSTRUCTED = "reconstructed"
SIGNAL_INTEGRAL = "integral"


@dataclass(slots=True)
class RawPipelineConfig:
    enabled: bool = True
    path: str = "run_raw.npz"
    compression: str = "none"
    dtype: str = "float64"


@dataclass(slots=True)
class SignalPipelineConfig:
    selected: list[str] = field(default_factory=lambda: ["t_s"])
    include_kinds: list[str] = field(default_factory=lambda: [SIGNAL_RAW, SIGNAL_DERIVATIVE, SIGNAL_RECONSTRUCTED, SIGNAL_INTEGRAL])
    remove_zero_columns: bool = True
    zero_tolerance: float = 0.0
    keep_zero_selected: bool = False


@dataclass(slots=True)
class CsvPipelineConfig:
    enabled: bool = True
    path: str = "signals.csv"
    separator: str = ";"
    include_units_row: bool = True
    include_kind_row: bool = True


@dataclass(slots=True)
class ResultsPipelineConfig:
    enabled: bool = False
    path: str = "csv/results.csv"
    include_units_row: bool = True
    include_kind_row: bool = True


@dataclass(slots=True)
class ReconstructionPipelineConfig:
    enabled: bool = True
    only_selected: bool = True


@dataclass(slots=True)
class IntegralsPipelineConfig:
    enabled: bool = True
    only_selected: bool = True
    cycle_mode: str = "full_run"
    absolute_heat_loss: bool = True


@dataclass(slots=True)
class SummaryPipelineConfig:
    enabled: bool = True
    path: str = "summary/run_summary.yaml"
    text_path: str | None = "summary/run_summary.txt"
    markdown_path: str | None = "README.md"


@dataclass(slots=True)
class LastUtOtUtPipelineConfig:
    enabled: bool = False
    path: str | None = None
    step_deg: float = 0.1
    axis_min_deg: float = 0.0
    axis_max_deg: float = 360.0
    axis_signal: str = "theta_deg"


@dataclass(slots=True)
class PlotPipelineEntryConfig:
    enabled: bool = True
    path: str = "plot.yaml"
    prefix: str = ""
    window: str = "all"


@dataclass(slots=True)
class PlotWindowPipelineConfig:
    enabled: bool = False
    layout_path: str | None = None
    output_dir: str | None = None
    prefix: str | None = None
    clean: bool = False


@dataclass(slots=True)
class PlotPipelineConfig:
    enabled: bool | None = None
    output_dir: str | None = None
    auto_create_defaults: bool | None = None
    layout_path: str | None = None
    prefix: str | None = None
    clean: bool = False
    last_ut_ot_ut: PlotWindowPipelineConfig = field(default_factory=PlotWindowPipelineConfig)
    entries: list[PlotPipelineEntryConfig] = field(default_factory=list)


@dataclass(slots=True)
class OfflinePipelineConfig:
    enabled: bool = True
    allow_reconstruction: bool = False
    allow_derivatives: bool = False


@dataclass(slots=True)
class PipelineConfig:
    version: int = 1
    raw: RawPipelineConfig = field(default_factory=RawPipelineConfig)
    signals: SignalPipelineConfig = field(default_factory=SignalPipelineConfig)
    csv: CsvPipelineConfig = field(default_factory=CsvPipelineConfig)
    results: ResultsPipelineConfig = field(default_factory=ResultsPipelineConfig)
    reconstruction: ReconstructionPipelineConfig = field(default_factory=ReconstructionPipelineConfig)
    integrals: IntegralsPipelineConfig = field(default_factory=IntegralsPipelineConfig)
    summary: SummaryPipelineConfig = field(default_factory=SummaryPipelineConfig)
    last_ut_ot_ut: LastUtOtUtPipelineConfig = field(default_factory=LastUtOtUtPipelineConfig)
    plots: PlotPipelineConfig = field(default_factory=PlotPipelineConfig)
    offline: OfflinePipelineConfig = field(default_factory=OfflinePipelineConfig)


@dataclass(slots=True)
class SignalSpec:
    name: str
    unit: str
    kind: str
    family: str = ""
    component: str = ""
    source: str = ""


@dataclass(slots=True)
class PipelineArtifacts:
    raw_archive_path: str | None = None
    csv_path: str | None = None
    results_csv_path: str | None = None
    last_ut_ot_ut_csv_path: str | None = None
    summary_path: str | None = None
    summary_text_path: str | None = None
    summary_markdown_path: str | None = None
    generated_plot_paths: list[str] = field(default_factory=list)
    plot_layout_paths: list[str] = field(default_factory=list)
    signal_specs: dict[str, SignalSpec] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)


def _as_mapping(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _merge_dataclass(instance, data: dict[str, Any]):
    for key, value in data.items():
        if not hasattr(instance, key):
            continue
        current = getattr(instance, key)
        if hasattr(current, "__dataclass_fields__") and isinstance(value, dict):
            _merge_dataclass(current, value)
        elif key == "entries" and isinstance(instance, PlotPipelineConfig) and isinstance(value, list):
            entries: list[PlotPipelineEntryConfig] = []
            for item in value:
                entry = PlotPipelineEntryConfig()
                if isinstance(item, dict):
                    _merge_dataclass(entry, item)
                entries.append(entry)
            setattr(instance, key, entries)
        else:
            setattr(instance, key, value)
    return instance


def load_pipeline_config(path: Path | None) -> PipelineConfig:
    cfg = PipelineConfig()
    if path is None or not path.exists():
        return cfg
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return _merge_dataclass(cfg, _as_mapping(data))


def _unit_from_name(name: str) -> str:
    suffixes = (
        ("_rad_per_s", "rad/s"),
        ("_m_per_s2", "m/s2"),
        ("_m_per_s", "m/s"),
        ("_kg_per_s", "kg/s"),
        ("_W_per_m2K", "W/m2K"),
        ("_KW_per_m2K", "K*W/m2K"),
        ("_0to1", "1"),
        ("_Pa", "Pa"),
        ("_bar", "bar"),
        ("_K", "K"),
        ("_kg", "kg"),
        ("_Nm", "Nm"),
        ("_J", "J"),
        ("_W", "W"),
        ("_m3", "m3"),
        ("_m2", "m2"),
        ("_m", "m"),
        ("_rad", "rad"),
        ("_deg", "deg"),
        ("_s", "s"),
    )
    for suffix, unit in suffixes:
        if name.endswith(suffix):
            return unit
    if name == "cycle_index":
        return "1"
    return "1"


def _state_derivative_unit(state_label: str) -> str:
    label = str(state_label)
    unit_suffixes = (
        ("_m_per_s", "m/s2"),
        ("_kg_per_s", "kg/s2"),
        ("_W_per_m2K", "W/m2K/s"),
        ("_KW_per_m2K", "K*W/m2K/s"),
        ("_kg", "kg/s"),
        ("_J", "W"),
        ("_K", "K/s"),
        ("_Pa", "Pa/s"),
        ("_m", "m/s"),
    )
    for suffix, unit in unit_suffixes:
        if label.endswith(suffix):
            return unit
    return "1/s"


def _family_component(name: str) -> tuple[str, str]:
    parts = str(name).split("_")
    if len(parts) >= 2 and parts[1].isdigit():
        return parts[0], f"{parts[0]}_{parts[1]}"
    return parts[0] if parts else "", parts[0] if parts else ""


def _state_names(bundle) -> list[str]:
    layout = getattr(bundle, "state_layout", None)
    if layout is None:
        return []
    try:
        return list(layout.state_labels(volume_names=list(getattr(bundle, "volume_names", []) or [])))
    except Exception:
        return [f"state_{i}" for i in range(int(getattr(bundle, "y_init", np.zeros(0)).shape[0]))]


def _raw_signal_name(state_name: str) -> str:
    return str(state_name)


def _raw_solver_state_key(bundle, state_name: str) -> str:
    key = _raw_signal_name(state_name)
    fp = getattr(bundle, "free_piston", None)
    if fp is None:
        return key
    if str(getattr(fp, "kinematics_type", "linear") or "linear") != "oscillating_rotary":
        return key
    if key == "free_piston_x_m":
        return "free_piston_q_rad"
    if key == "free_piston_v_m_per_s":
        return "free_piston_q_dot_rad_per_s"
    return key


def _config_hash(config_path: Path) -> str:
    try:
        return hashlib.sha256(config_path.read_bytes()).hexdigest()
    except Exception:
        return ""


def _is_zero_column(values: np.ndarray, tolerance: float) -> bool:
    arr = np.asarray(values)
    if arr.size == 0:
        return True
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return True
    return bool(np.max(np.abs(finite)) <= max(float(tolerance), 0.0))


def _integral_source_for_key(key: str) -> tuple[str, str] | None:
    power_suffixes = {
        "_wall_heat_cycle_J": "_wall_heat_W",
        "_wall_cylinder_heat_cycle_J": "_wall_cylinder_heat_W",
        "_wall_head_heat_cycle_J": "_wall_head_heat_W",
        "_wall_piston_heat_cycle_J": "_wall_piston_heat_W",
        "_wall_heat_zones_sum_cycle_J": "_wall_heat_zones_sum_W",
        "_added_energy_cycle_J": "_added_energy_W",
        "_enthalpy_in_cycle_J": "_enthalpy_in_W",
        "_enthalpy_out_cycle_J": "_enthalpy_out_W",
        "_piston_work_cycle_J": "_piston_work_W",
        "_evaporation_sink_cycle_J": "_evaporation_sink_W",
    }
    flow_suffixes = {
        "_mdot_in_cycle_kg": "_mdot_in_kg_per_s",
        "_mdot_out_cycle_kg": "_mdot_out_kg_per_s",
    }
    for target_suffix, source_suffix in {**power_suffixes, **flow_suffixes}.items():
        if key.endswith(target_suffix):
            return key[: -len(target_suffix)] + source_suffix, target_suffix
    return None


def _cycle_integral(t_s: np.ndarray, values: np.ndarray, cycle_index: np.ndarray, *, absolute: bool) -> np.ndarray:
    t = np.asarray(t_s, dtype=np.float64)
    y = np.asarray(values, dtype=np.float64)
    cycles = np.asarray(cycle_index, dtype=np.int64)
    out = np.zeros(t.shape[0], dtype=np.float64)
    if t.size <= 1:
        return out
    for i in range(1, t.shape[0]):
        if cycles[i] != cycles[i - 1]:
            out[i] = 0.0
            continue
        dt = max(0.0, float(t[i]) - float(t[i - 1]))
        a = float(y[i - 1])
        b = float(y[i])
        if absolute:
            a = abs(a)
            b = abs(b)
        out[i] = out[i - 1] + 0.5 * (a + b) * dt
    return out


def _grid_targets(start: float, stop: float, step: float, *, include_endpoint: bool = True) -> np.ndarray:
    if step <= 0.0 or stop < start:
        return np.zeros(0, dtype=np.float64)
    n = int(np.floor((stop - start) / step + 1.0e-12)) + 1
    values = start + np.arange(max(n, 0), dtype=np.float64) * step
    values = values[values <= stop + 1.0e-12]
    if include_endpoint and (values.size == 0 or abs(float(values[-1]) - stop) > max(1.0e-12, abs(step) * 1.0e-9)):
        values = np.concatenate([values, np.asarray([stop], dtype=np.float64)])
    return values


def _scalar_npz_value(raw: Any) -> str:
    arr = np.asarray(raw)
    if arr.size == 0:
        return ""
    return str(arr.reshape(-1)[0])


def _as_text_list(raw: Any) -> list[str]:
    return [str(value) for value in np.asarray(raw).reshape(-1).tolist()]


def _safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if np.isfinite(out) else None


def _series_extrema(columns: dict[str, np.ndarray], suffixes: tuple[str, ...], *, reducer: str) -> dict[str, Any]:
    matches: dict[str, float] = {}
    for key, values in columns.items():
        if not any(str(key).endswith(suffix) for suffix in suffixes):
            continue
        arr = np.asarray(values, dtype=np.float64)
        finite = arr[np.isfinite(arr)]
        if finite.size == 0:
            continue
        matches[key] = float(np.max(finite) if reducer == "max" else np.min(finite))
    if not matches:
        return {"value": None, "signal": None}
    signal, value = max(matches.items(), key=lambda item: item[1]) if reducer == "max" else min(matches.items(), key=lambda item: item[1])
    return {"value": value, "signal": signal}


def _flat_value(value: Any, unit: str, *, source: str | None = None, label: str | None = None) -> dict[str, Any]:
    return {
        "value": _safe_float(value) if isinstance(value, (int, float, np.floating, np.integer)) else value,
        "unit": unit,
        "source": source,
        "label": label,
    }


def _finite_min_max(values: Any) -> tuple[float | None, float | None]:
    arr = np.asarray(values, dtype=np.float64)
    finite = arr[np.isfinite(arr)]
    if finite.size == 0:
        return None, None
    return float(np.min(finite)), float(np.max(finite))


def _detected_cycle_count(bundle, t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray, architecture: str) -> tuple[int, str]:
    cycles = np.asarray(cycle_indices, dtype=np.int64)
    cycle_index_count = int(np.unique(cycles).size) if cycles.size else 0
    configured_count = int(getattr(getattr(bundle, "simulation", None), "total_cycles", 0) or 0)
    if str(architecture) != "free_piston":
        return cycle_index_count, "cycle_index"

    turning_count = 0
    fp = getattr(bundle, "free_piston", None)
    y_arr = np.asarray(y, dtype=np.float64)
    if fp is not None and y_arr.ndim == 2:
        x_idx = int(getattr(fp, "x_state_index", -1))
        v_idx = int(getattr(fp, "v_state_index", -1))
        if 0 <= x_idx < y_arr.shape[0] and 0 <= v_idx < y_arr.shape[0]:
            v_arr = np.asarray(y_arr[v_idx], dtype=np.float64)
            max_v = float(np.max(np.abs(v_arr))) if v_arr.size else 0.0
            turning_count = count_ut_ot_ut_cycles(
                np.asarray(t, dtype=np.float64),
                np.asarray(y_arr[x_idx], dtype=np.float64),
                v_arr,
                eps=max(1.0e-10, 1.0e-6 * max_v),
            )
    if configured_count > 0:
        return max(configured_count, turning_count, cycle_index_count), "simulation.total_cycles"
    if turning_count > 0:
        return turning_count, "turning_points"
    return cycle_index_count, "cycle_index"


def _summary_values(
    *,
    columns: dict[str, np.ndarray],
    pmax: dict[str, Any],
    tmax: dict[str, Any],
    xmin: dict[str, Any],
    xmax: dict[str, Any],
    duration: float | None,
    unique_cycles: np.ndarray,
    cycle_count: int,
    cycle_count_source: str,
) -> dict[str, dict[str, Any]]:
    values: dict[str, dict[str, Any]] = {
        "duration_s": _flat_value(duration, "s", source="simulation.duration_s", label="Simulationsdauer"),
        "duration_ms": _flat_value(duration * 1000.0 if duration is not None else None, "ms", source="simulation.duration_s", label="Simulationsdauer"),
        "frequency_Hz": _flat_value(float(cycle_count) / duration if duration is not None and duration > 0.0 else None, "Hz", source=cycle_count_source, label="Zyklusfrequenz"),
        "cycles_detected": _flat_value(int(cycle_count), "1", source=cycle_count_source, label="Erkannte Zyklen"),
        "cycle_last": _flat_value(int(unique_cycles[-1]) if unique_cycles.size else None, "1", source="cycle_index", label="Letzter Zyklusindex"),
        "pmax_bar": _flat_value(pmax["value"] / 1e5 if pmax["value"] is not None else None, "bar", source=pmax.get("signal"), label="Maximaler Druck"),
        "Tmax_K": _flat_value(tmax.get("value"), "K", source=tmax.get("signal"), label="Maximale Temperatur"),
        "x_min_mm": _flat_value(xmin["value"] * 1000.0 if xmin["value"] is not None else None, "mm", source=xmin.get("signal"), label="Kleinste Kolbenposition"),
        "x_max_mm": _flat_value(xmax["value"] * 1000.0 if xmax["value"] is not None else None, "mm", source=xmax.get("signal"), label="Groesste Kolbenposition"),
        "stroke_mm": _flat_value((xmax["value"] - xmin["value"]) * 1000.0 if xmax["value"] is not None and xmin["value"] is not None else None, "mm", source=f"{xmin.get('signal')}..{xmax.get('signal')}", label="Hubfenster"),
    }
    for key, unit, scale, label in (
        ("free_piston_generator_power_W", "W", 1.0, "Generatorleistung"),
        ("free_piston_F_net_N", "N", 1.0, "Netto-Kolbenkraft"),
        ("cylinder_1_p_Pa", "bar", 1.0e-5, "Zylinder 1 Druck"),
        ("cylinder_2_p_Pa", "bar", 1.0e-5, "Zylinder 2 Druck"),
        ("cylinder_1_T_K", "K", 1.0, "Zylinder 1 Temperatur"),
        ("cylinder_2_T_K", "K", 1.0, "Zylinder 2 Temperatur"),
    ):
        if key not in columns:
            continue
        min_value, max_value = _finite_min_max(columns[key])
        values[f"{key}_min"] = _flat_value(min_value * scale if min_value is not None else None, unit, source=key, label=f"{label} min")
        values[f"{key}_max"] = _flat_value(max_value * scale if max_value is not None else None, unit, source=key, label=f"{label} max")
    return values


def _summary_dict(
    *,
    bundle,
    config_path: Path,
    cfg_path: Path | None,
    raw_path: str | None,
    csv_path: str | None,
    columns: dict[str, np.ndarray],
    specs: dict[str, SignalSpec],
    t: np.ndarray,
    y: np.ndarray,
    cycle_indices: np.ndarray,
    architecture: str,
    mode: str,
) -> dict[str, Any]:
    t_arr = np.asarray(t, dtype=np.float64)
    cycles = np.asarray(cycle_indices, dtype=np.int64)
    finite_t = t_arr[np.isfinite(t_arr)]
    t_start = float(finite_t[0]) if finite_t.size else None
    t_end = float(finite_t[-1]) if finite_t.size else None
    duration = float(t_end - t_start) if t_start is not None and t_end is not None else None
    unique_cycles = np.unique(cycles) if cycles.size else np.zeros(0, dtype=np.int64)
    cycle_count, cycle_count_source = _detected_cycle_count(bundle, t_arr, y, cycles, architecture)
    pmax = _series_extrema(columns, ("_p_Pa", "_pressure_Pa"), reducer="max")
    tmax = _series_extrema(columns, ("_T_K", "_temperature_K"), reducer="max")
    xmax = _series_extrema(columns, ("_x_m",), reducer="max")
    xmin = _series_extrema(columns, ("_x_m",), reducer="min")
    values = _summary_values(columns=columns, pmax=pmax, tmax=tmax, xmin=xmin, xmax=xmax, duration=duration, unique_cycles=unique_cycles, cycle_count=cycle_count, cycle_count_source=cycle_count_source)
    return {
        "schema_version": 1,
        "mode": mode,
        "config": {
            "path": str(config_path),
            "hash": _config_hash(config_path) if config_path.exists() else "",
            "pipeline_config": str(cfg_path) if cfg_path is not None else None,
        },
        "simulation": {
            "architecture": architecture,
            "samples": int(t_arr.shape[0]),
            "states": int(y.shape[0]) if y.ndim >= 1 else 0,
            "cycles_detected": int(cycle_count),
            "cycles_detected_source": cycle_count_source,
            "cycle_first": int(unique_cycles[0]) if unique_cycles.size else None,
            "cycle_last": int(unique_cycles[-1]) if unique_cycles.size else None,
            "t_start_s": t_start,
            "t_end_s": t_end,
            "duration_s": duration,
        },
        "extrema": {
            "pmax_Pa": pmax["value"],
            "pmax_bar": _safe_float(pmax["value"] / 1e5) if pmax["value"] is not None else None,
            "pmax_signal": pmax["signal"],
            "Tmax_K": tmax["value"],
            "Tmax_signal": tmax["signal"],
            "xmax_m": xmax["value"],
            "xmax_signal": xmax["signal"],
            "xmin_m": xmin["value"],
            "xmin_signal": xmin["signal"],
        },
        "signals": {
            "exported": len(specs),
            "by_kind": {
                kind: sum(1 for spec in specs.values() if spec.kind == kind)
                for kind in (SIGNAL_RAW, SIGNAL_DERIVATIVE, SIGNAL_RECONSTRUCTED, SIGNAL_INTEGRAL)
            },
        },
        "outputs": {
            "raw_archive": raw_path,
            "csv": csv_path,
        },
        "values": values,
    }


def _summary_text(summary: dict[str, Any]) -> str:
    sim = summary.get("simulation", {})
    ext = summary.get("extrema", {})
    outputs = summary.get("outputs", {})
    lines = [
        "Thermo0D Pipeline Run Summary",
        "",
        f"Mode: {summary.get('mode')}",
        f"Architecture: {sim.get('architecture')}",
        f"Samples: {sim.get('samples')}",
        f"Cycles detected: {sim.get('cycles_detected')}",
        f"Duration [s]: {sim.get('duration_s')}",
        f"pmax [bar]: {ext.get('pmax_bar')} ({ext.get('pmax_signal')})",
        f"Tmax [K]: {ext.get('Tmax_K')} ({ext.get('Tmax_signal')})",
        f"x range [m]: {ext.get('xmin_m')} .. {ext.get('xmax_m')}",
        "",
        f"Raw archive: {outputs.get('raw_archive')}",
        f"CSV: {outputs.get('csv')}",
    ]
    return "\n".join(lines).rstrip() + "\n"


class PipelineSummaryWriter:
    @staticmethod
    def write(
        path: Path,
        *,
        summary: dict[str, Any],
        text_path: Path | None = None,
    ) -> tuple[str, str | None]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(summary, sort_keys=False, allow_unicode=True), encoding="utf-8")
        text_out: str | None = None
        if text_path is not None:
            text_path.parent.mkdir(parents=True, exist_ok=True)
            text_path.write_text(_summary_text(summary), encoding="utf-8")
            text_out = str(text_path)
        return str(path), text_out


class RawArchive:
    @staticmethod
    def write(path: Path, *, t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray, bundle, config_path: Path, dtype: str, compression: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        target_dtype = np.float32 if str(dtype).lower() == "float32" else np.float64
        state_names = np.asarray(_state_names(bundle), dtype=str)
        state_units = np.asarray([_unit_from_name(name) for name in state_names], dtype=str)
        payload = {
            "schema_version": np.asarray([1], dtype=np.int64),
            "t_s": np.asarray(t, dtype=target_dtype),
            "y": np.asarray(y, dtype=target_dtype),
            "cycle_index": np.asarray(cycle_indices, dtype=np.int64),
            "state_names": state_names,
            "state_units": state_units,
            "architecture": np.asarray([str(getattr(bundle, "architecture", "classic"))], dtype=str),
            "config_path": np.asarray([str(config_path)], dtype=str),
            "config_hash": np.asarray([_config_hash(config_path)], dtype=str),
        }
        if str(compression).lower() == "compressed":
            np.savez_compressed(path, **payload)
        else:
            np.savez(path, **payload)

    @staticmethod
    def read(path: Path) -> dict[str, Any]:
        with np.load(path, allow_pickle=False) as raw:
            return {key: raw[key].copy() for key in raw.files}


class _RawArchiveLayout:
    def __init__(self, state_names: list[str]) -> None:
        self._state_names = list(state_names)

    def state_labels(self, volume_names=None):
        return list(self._state_names)


def _bundle_from_raw_archive(raw: dict[str, Any], *, outdir: str | None = None) -> SimpleNamespace:
    state_names = _as_text_list(raw.get("state_names", []))
    architecture = _scalar_npz_value(raw.get("architecture", "classic")) or "classic"
    return SimpleNamespace(
        architecture=architecture,
        postprocessing=SimpleNamespace(outdir=outdir, pipeline_config=None),
        state_layout=_RawArchiveLayout(state_names),
        volume_names=[],
        y_init=np.zeros(len(state_names), dtype=np.float64),
    )


def _offline_bundle_from_config_or_raw(raw: dict[str, Any], config_path: Path, *, outdir: str | None = None):
    if config_path.is_file():
        try:
            from thermo0d.input.config_loader import ConfigLoader
            from thermo0d.input.model_builder import build_model_bundle

            config = ConfigLoader.load(config_path)
            bundle = build_model_bundle(config, config_path)
            raw_state_names = _as_text_list(raw.get("state_names", []))
            bundle_state_names = _state_names(bundle)
            if raw_state_names and bundle_state_names and raw_state_names != bundle_state_names:
                ConsoleArtifactReporter.print_status(
                    "offline:bundle",
                    "warn",
                    reason="state-layout-mismatch; using raw archive layout only",
                )
                return _bundle_from_raw_archive(raw, outdir=outdir)
            if outdir is not None and getattr(bundle, "postprocessing", None) is not None:
                bundle.postprocessing.outdir = str(outdir)
            return bundle
        except Exception as exc:
            ConsoleArtifactReporter.print_status(
                "offline:bundle",
                "warn",
                reason=f"full-config-load-failed: {exc}",
            )
    return _bundle_from_raw_archive(raw, outdir=outdir)


class PipelinePostprocessingService:
    def __init__(self, bundle, config_path: str | Path, *, result_dir: str | Path | None = None):
        self.bundle = bundle
        self.config_path = Path(config_path).resolve()
        if result_dir is not None:
            self.result_dir = Path(result_dir).resolve()
        else:
            self.result_dir = PathManager.resolve_output_dir(
                self.config_path,
                str(getattr(bundle.postprocessing, "outdir", "") or "").strip() or None,
            )

    def _pipeline_config_path(self) -> Path | None:
        raw = str(getattr(self.bundle.postprocessing, "pipeline_config", "") or "").strip()
        if not raw:
            return None
        path = Path(raw)
        if not path.is_absolute():
            path = self.config_path.parent / path
        return path.resolve()

    def _resolve_pipeline_output(self, path_text: str) -> Path:
        path = Path(str(path_text).strip() or "signals.csv")
        if path.is_absolute():
            return path
        return (self.result_dir / path).resolve()

    def _plot_output_dir(self, cfg: PipelineConfig, window: str = "all") -> Path:
        if str(window or "").strip().lower() in {"last_ut_ot_ut", "last-complete-cycle", "last_complete_cycle"}:
            configured_window = str(cfg.plots.last_ut_ot_ut.output_dir or "").strip()
            if configured_window:
                path = Path(configured_window)
                return path.resolve() if path.is_absolute() else (self.result_dir / path).resolve()
        configured = str(cfg.plots.output_dir or "").strip()
        if configured:
            path = Path(configured)
            return path.resolve() if path.is_absolute() else (self.result_dir / path).resolve()
        return PathManager.resolve_plot_output_dir(
            self.config_path,
            str(getattr(self.bundle.postprocessing, "outdir", "") or "").strip() or None,
        )

    def _plots_enabled(self, cfg: PipelineConfig) -> bool:
        if cfg.plots.enabled is not None:
            return bool(cfg.plots.enabled)
        if not hasattr(self.bundle, "vol_matrix"):
            return False
        return bool(getattr(self.bundle.postprocessing, "plots_enabled", False))

    def _plot_auto_create_defaults(self, cfg: PipelineConfig) -> bool:
        if cfg.plots.auto_create_defaults is not None:
            return bool(cfg.plots.auto_create_defaults)
        return bool(getattr(self.bundle.postprocessing, "plot_layout_auto_create_defaults", False))

    def _default_plot_entries(self) -> list[PlotPipelineEntryConfig]:
        return [
            PlotPipelineEntryConfig(enabled=True, path="plot.yaml", prefix="", window="all"),
            PlotPipelineEntryConfig(enabled=True, path="plot10.yaml", prefix="plot10", window="all"),
        ]

    def _resolve_plot_layout_dir(self, path_text: str | None) -> Path | None:
        raw = str(path_text or "").strip()
        if not raw:
            return None
        path = Path(raw)
        if path.is_absolute():
            return path.resolve()
        return (self.config_path.parent / path).resolve()

    def _last_ut_ot_ut_plot_entries_from_legacy_config(self, cfg: PipelineConfig) -> list[PlotPipelineEntryConfig]:
        if not bool(cfg.plots.last_ut_ot_ut.enabled):
            return []
        layout_dir = self._resolve_plot_layout_dir(cfg.plots.last_ut_ot_ut.layout_path)
        entries: list[PlotPipelineEntryConfig] = []
        if layout_dir is not None and layout_dir.is_dir():
            for layout_path in sorted(layout_dir.glob("*.yaml")):
                entries.append(
                    PlotPipelineEntryConfig(
                        enabled=True,
                        path=str(layout_path),
                        prefix=str(cfg.plots.last_ut_ot_ut.prefix or layout_path.stem),
                        window="last_ut_ot_ut",
                    )
                )
            if entries:
                return entries
        bundle_entries = list(getattr(self.bundle.postprocessing, "plot_layout_entries", []) or [])
        for entry in bundle_entries:
            if not bool(getattr(entry, "enabled", True)):
                continue
            entries.append(
                PlotPipelineEntryConfig(
                    enabled=True,
                    path=str(getattr(entry, "path", "") or ""),
                    prefix=str(cfg.plots.last_ut_ot_ut.prefix or getattr(entry, "prefix", "") or ""),
                    window="last_ut_ot_ut",
                )
            )
        return entries

    def _all_plot_entries_from_legacy_config(self, cfg: PipelineConfig) -> list[PlotPipelineEntryConfig]:
        layout_dir = self._resolve_plot_layout_dir(cfg.plots.layout_path)
        entries: list[PlotPipelineEntryConfig] = []
        if layout_dir is not None and layout_dir.is_dir():
            for layout_path in sorted(layout_dir.glob("*.yaml")):
                entries.append(
                    PlotPipelineEntryConfig(
                        enabled=True,
                        path=str(layout_path),
                        prefix=str(cfg.plots.prefix or layout_path.stem),
                        window="all",
                    )
                )
            if entries:
                return entries
        bundle_entries = list(getattr(self.bundle.postprocessing, "plot_layout_entries", []) or [])
        for entry in bundle_entries:
            entries.append(
                PlotPipelineEntryConfig(
                    enabled=bool(getattr(entry, "enabled", True)),
                    path=str(getattr(entry, "path", "") or ""),
                    prefix=str(getattr(entry, "prefix", "") or ""),
                    window=str(getattr(entry, "window", "all") or "all"),
                )
            )
        return entries

    def _configured_plot_entries(self, cfg: PipelineConfig) -> list[PlotPipelineEntryConfig]:
        if cfg.plots.entries:
            return list(cfg.plots.entries)
        entries = self._all_plot_entries_from_legacy_config(cfg)
        legacy_last_entries = self._last_ut_ot_ut_plot_entries_from_legacy_config(cfg)
        if legacy_last_entries:
            existing = {(str(entry.path), str(entry.window or "all")) for entry in entries}
            for entry in legacy_last_entries:
                key = (str(entry.path), str(entry.window or "all"))
                if key not in existing:
                    entries.append(entry)
                    existing.add(key)
        if not entries and self._plot_auto_create_defaults(cfg):
            entries = self._default_plot_entries()
        return entries

    def _prepare_plot_layouts(self, cfg: PipelineConfig) -> list[tuple[PlotPipelineEntryConfig, Path]]:
        if not self._plots_enabled(cfg):
            return []
        auto_defaults = self._plot_auto_create_defaults(cfg)
        resolved: list[tuple[PlotPipelineEntryConfig, Path]] = []
        for entry in self._configured_plot_entries(cfg):
            if not bool(entry.enabled):
                continue
            path_text = str(entry.path or "").strip()
            if not path_text:
                continue
            layout_path = PathManager.resolve_layout_path(
                self.config_path,
                path_text,
                configured_outdir=str(getattr(self.bundle.postprocessing, "outdir", "") or "").strip() or None,
                prefer_output_dir_when_missing=auto_defaults,
            )
            if auto_defaults and not layout_path.exists() and hasattr(self.bundle, "vol_matrix"):
                name = layout_path.name.lower()
                if name == "plot.yaml":
                    ensure_default_plot_yaml(self.bundle, self.config_path, output_path=layout_path)
                elif name == "plot10.yaml":
                    ensure_default_plot10_yaml(self.bundle, self.config_path, output_path=layout_path)
            resolved.append((entry, layout_path))
        return resolved

    @staticmethod
    def _plot_layout_signal_keys(layout_path: Path) -> set[str]:
        if not layout_path.exists() or not layout_path.is_file():
            return set()
        try:
            data = yaml.safe_load(layout_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return set()
        keys: set[str] = set()
        figures = data.get("figures") if isinstance(data.get("figures"), list) else []
        for figure in figures:
            subplots = figure.get("subplots") if isinstance(figure, dict) and isinstance(figure.get("subplots"), list) else []
            for subplot in subplots:
                if not isinstance(subplot, dict):
                    continue
                x_signal = str(subplot.get("x_signal", "") or "").strip()
                if x_signal:
                    keys.add(x_signal)
                series = subplot.get("series") if isinstance(subplot.get("series"), list) else []
                for item in series:
                    if not isinstance(item, dict):
                        continue
                    key = str(item.get("signal_key", "") or "").strip()
                    if key:
                        keys.add(key)
                for box_name in ("text_box", "info_box"):
                    box = subplot.get(box_name)
                    if not isinstance(box, dict):
                        continue
                    metrics = box.get("metrics") if isinstance(box.get("metrics"), list) else []
                    for metric in metrics:
                        if not isinstance(metric, dict):
                            continue
                        for field in ("signal_key", "x_signal", "pressure_signal", "volume_signal"):
                            key = str(metric.get(field, "") or "").strip()
                            if key:
                                keys.add(key)
                        if str(metric.get("kind", "") or "").lower().strip() == "imep":
                            cylinder = str(metric.get("cylinder", "") or "").strip()
                            if cylinder:
                                keys.add(f"{cylinder}_p_Pa")
                                keys.add(f"{cylinder}_V_m3")
        return keys

    @staticmethod
    def _columns_to_rows(keys: list[str], columns: dict[str, np.ndarray]) -> list[dict[str, float | int]]:
        usable = [key for key in keys if key in columns]
        if not usable:
            return []
        n_rows = min(int(np.asarray(columns[key]).shape[0]) for key in usable)
        rows: list[dict[str, float | int]] = []
        arrays = {key: np.asarray(columns[key]) for key in usable}
        for idx in range(n_rows):
            row: dict[str, float | int] = {}
            for key, arr in arrays.items():
                value = arr[idx]
                if key == "cycle_index" or np.issubdtype(np.asarray(arr).dtype, np.integer):
                    row[key] = int(value)
                else:
                    row[key] = float(value)
            rows.append(row)
        return rows

    def _raw_columns(self, t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray) -> tuple[dict[str, np.ndarray], dict[str, SignalSpec]]:
        columns: dict[str, np.ndarray] = {
            "t_s": np.asarray(t, dtype=np.float64),
            "cycle_index": np.asarray(cycle_indices, dtype=np.int64),
        }
        specs: dict[str, SignalSpec] = {
            "t_s": SignalSpec("t_s", "s", SIGNAL_RAW, "time", "time", "solver"),
            "cycle_index": SignalSpec("cycle_index", "1", SIGNAL_RAW, "cycle", "cycle", "analysis"),
        }
        for idx, state_name in enumerate(_state_names(self.bundle)):
            if idx >= int(y.shape[0]):
                continue
            key = _raw_solver_state_key(self.bundle, state_name)
            family, component = _family_component(key)
            columns[key] = np.asarray(y[idx], dtype=np.float64)
            specs[key] = SignalSpec(key, _unit_from_name(key), SIGNAL_RAW, family, component, "solver_state")
        return columns, specs

    def _selected_keys(self, cfg: PipelineConfig) -> list[str]:
        keys = [str(key).strip() for key in list(cfg.signals.selected or []) if str(key).strip()]
        return keys or ["t_s"]

    def _needed_reconstructed_keys(self, selected: list[str], include_kinds: set[str]) -> set[str]:
        needed: set[str] = set()
        if SIGNAL_RECONSTRUCTED in include_kinds:
            needed.update(selected)
        if SIGNAL_INTEGRAL in include_kinds:
            for key in selected:
                source = _integral_source_for_key(key)
                if source is not None:
                    needed.add(source[0])
        return needed

    def _needed_derivative_indices(self, selected: list[str], include_kinds: set[str]) -> dict[int, str]:
        if SIGNAL_DERIVATIVE not in include_kinds:
            return {}
        state_names = _state_names(self.bundle)
        by_name = {name: idx for idx, name in enumerate(state_names)}
        needed: dict[int, str] = {}
        for key in selected:
            if not key.startswith("d_") or not key.endswith("_dt"):
                continue
            state_name = key[2:-3]
            if "_wall_temperature_" in state_name:
                continue
            idx = by_name.get(state_name)
            if idx is not None:
                needed[idx] = key
        return needed

    def _add_reconstructed_columns(self, columns: dict[str, np.ndarray], specs: dict[str, SignalSpec], t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray, requested: set[str]) -> None:
        if not requested:
            return
        series = SignalReconstructionService.build(self.bundle, t, y, cycle_indices, requested_keys=requested)
        for key, values in series.as_columns().items():
            if key in ("t_s", "cycle_index"):
                continue
            family, component = _family_component(key)
            columns[key] = np.asarray(values)
            specs[key] = SignalSpec(key, _unit_from_name(key), SIGNAL_RECONSTRUCTED, family, component, "reconstruction")

    @staticmethod
    def _snapshot_free_piston_runtime(bundle) -> tuple[object | None, dict[str, object]]:
        fp = getattr(bundle, "free_piston", None)
        if fp is None:
            return None, {}
        fields = getattr(fp, "__dataclass_fields__", {})
        names = [name for name in fields if str(name).startswith("runtime_")]
        snapshot: dict[str, object] = {}
        for name in names:
            value = getattr(fp, name)
            snapshot[name] = value.copy() if isinstance(value, np.ndarray) else value
        return fp, snapshot

    @staticmethod
    def _restore_free_piston_runtime(fp, snapshot: dict[str, object]) -> None:
        if fp is None:
            return
        for name, value in snapshot.items():
            current = getattr(fp, name, None)
            if isinstance(current, np.ndarray) and isinstance(value, np.ndarray) and current.shape == value.shape:
                current[...] = value
            else:
                setattr(fp, name, value)

    def _update_free_piston_runtime_before_rhs(self, t_s: float, y_state: np.ndarray) -> None:
        if getattr(self.bundle, "architecture", "classic") != "free_piston":
            return
        try:
            from thermo0d.model.free_piston.combustion_latch import (
                free_piston_uses_slot_closure_lambda,
                free_piston_uses_time_vibe,
                free_piston_uses_vapor_injector,
                update_free_piston_combustion_latch_state,
            )
        except Exception:
            return
        if not (
            free_piston_uses_slot_closure_lambda(self.bundle)
            or free_piston_uses_vapor_injector(self.bundle)
            or free_piston_uses_time_vibe(self.bundle)
        ):
            return
        update_free_piston_combustion_latch_state(self.bundle, float(t_s), np.asarray(y_state, dtype=np.float64))

    def _add_derivative_columns(self, columns: dict[str, np.ndarray], specs: dict[str, SignalSpec], t: np.ndarray, y: np.ndarray, requested: dict[int, str]) -> None:
        if not requested:
            return
        from thermo0d.compute.executor import build_rhs_for_bundle

        rhs = build_rhs_for_bundle(self.bundle)
        n = int(t.shape[0])
        buffers = {idx: np.zeros(n, dtype=np.float64) for idx in requested}
        fp, runtime_snapshot = self._snapshot_free_piston_runtime(self.bundle)
        try:
            for k in range(n):
                t_value = float(t[k])
                y_state = np.asarray(y[:, k], dtype=np.float64)
                self._update_free_piston_runtime_before_rhs(t_value, y_state)
                dy = np.asarray(rhs(t_value, y_state.copy()), dtype=np.float64)
                for idx, buffer in buffers.items():
                    buffer[k] = float(dy[idx]) if idx < int(dy.shape[0]) else 0.0
        finally:
            self._restore_free_piston_runtime(fp, runtime_snapshot)

        state_names = _state_names(self.bundle)
        for idx, key in requested.items():
            state_name = state_names[idx] if idx < len(state_names) else key[2:-3]
            family, component = _family_component(key)
            columns[key] = buffers[idx]
            specs[key] = SignalSpec(key, _state_derivative_unit(state_name), SIGNAL_DERIVATIVE, family, component, "rhs")

    def _add_integral_columns(self, columns: dict[str, np.ndarray], specs: dict[str, SignalSpec], selected: list[str], cfg: PipelineConfig) -> None:
        if "t_s" not in columns or "cycle_index" not in columns:
            return
        for key in selected:
            source_info = _integral_source_for_key(key)
            if source_info is None:
                continue
            source_key, _target_suffix = source_info
            source = columns.get(source_key)
            if source is None:
                continue
            absolute = bool(cfg.integrals.absolute_heat_loss and "_wall_heat" in key)
            columns[key] = _cycle_integral(columns["t_s"], np.asarray(source, dtype=np.float64), columns["cycle_index"], absolute=absolute)
            family, component = _family_component(key)
            specs[key] = SignalSpec(key, _unit_from_name(key), SIGNAL_INTEGRAL, family, component, source_key)

    def _filter_selected_columns(self, columns: dict[str, np.ndarray], specs: dict[str, SignalSpec], selected: list[str], cfg: PipelineConfig) -> tuple[list[str], dict[str, np.ndarray], dict[str, SignalSpec]]:
        include_kinds = {str(kind).strip() for kind in cfg.signals.include_kinds if str(kind).strip()}
        out_keys: list[str] = []
        out_cols: dict[str, np.ndarray] = {}
        out_specs: dict[str, SignalSpec] = {}
        selected_set = set(selected)
        for key in selected:
            spec = specs.get(key)
            if spec is None or spec.kind not in include_kinds:
                continue
            arr = np.asarray(columns[key])
            if cfg.signals.remove_zero_columns and not cfg.signals.keep_zero_selected and key not in ("t_s", "cycle_index"):
                if _is_zero_column(arr, float(cfg.signals.zero_tolerance)):
                    continue
            out_keys.append(key)
            out_cols[key] = arr
            out_specs[key] = spec
        for key in ("t_s", "cycle_index"):
            if key not in selected_set and key in columns and key not in out_cols:
                spec = specs[key]
                if spec.kind in include_kinds:
                    out_keys.insert(0 if key == "t_s" else min(1, len(out_keys)), key)
                    out_cols[key] = columns[key]
                    out_specs[key] = spec
        return out_keys, out_cols, out_specs

    def _generated_result_keys(self, columns: dict[str, np.ndarray], selected: list[str]) -> list[str]:
        keys: list[str] = []
        for key in ("t_s", "cycle_index", "theta_deg", "theta_local_deg"):
            if key in columns and key not in keys:
                keys.append(key)
        for key in selected:
            if key in columns and key not in keys:
                keys.append(key)
        for key in columns:
            if key not in keys:
                keys.append(key)
        return keys

    def _csv_object_names(self) -> list[str]:
        names: list[str] = []
        for attr in ("volume_names", "boundary_names", "connection_names"):
            for name in list(getattr(self.bundle, attr, []) or []):
                text = str(name).strip()
                if text and text not in names:
                    names.append(text)
        if getattr(self.bundle, "architecture", "classic") == "free_piston" and "free_piston" not in names:
            names.append("free_piston")
        return names

    @staticmethod
    def _csv_object_match_key(key: str) -> str:
        text = str(key)
        if text.startswith("d_") and text.endswith("_dt"):
            return text[2:-3]
        return text

    def _group_csv_keys_by_object(self, keys: list[str]) -> list[str]:
        if not keys:
            return keys

        original = [key for key in keys if str(key).strip()]
        front_order = ("t_s", "cycle_index", "theta_deg", "theta_local_deg")
        grouped: list[str] = []
        used: set[str] = set()
        for key in front_order:
            if key in original and key not in used:
                grouped.append(key)
                used.add(key)

        object_names = self._csv_object_names()
        buckets: dict[str, list[str]] = {name: [] for name in object_names}
        match_names = sorted(object_names, key=len, reverse=True)
        rest: list[str] = []
        for key in original:
            if key in used:
                continue
            match_key = self._csv_object_match_key(key)
            object_name = None
            for name in match_names:
                if match_key.startswith(name + "_"):
                    object_name = name
                    break
            if object_name is None:
                rest.append(key)
            else:
                buckets[object_name].append(key)
            used.add(key)

        for name in object_names:
            grouped.extend(buckets[name])
        grouped.extend(rest)
        return grouped

    def _write_csv(self, path: Path, keys: list[str], columns: dict[str, np.ndarray], specs: dict[str, SignalSpec], cfg: PipelineConfig) -> str | None:
        if not keys:
            return None
        keys = self._group_csv_keys_by_object(keys)
        n_rows = int(np.asarray(columns[keys[0]]).shape[0])
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.writer(handle, delimiter=str(cfg.csv.separator or ";"))
            writer.writerow(keys)
            if cfg.csv.include_units_row:
                writer.writerow([specs[key].unit for key in keys])
            if cfg.csv.include_kind_row:
                writer.writerow([specs[key].kind for key in keys])
            arrays = [np.asarray(columns[key]) for key in keys]
            for i in range(n_rows):
                writer.writerow([arr[i].item() if hasattr(arr[i], "item") else arr[i] for arr in arrays])
        return str(path)

    def _write_results_csv(self, path: Path, keys: list[str], columns: dict[str, np.ndarray], specs: dict[str, SignalSpec], cfg: PipelineConfig) -> str | None:
        csv_cfg = cfg.csv
        original_units = csv_cfg.include_units_row
        original_kinds = csv_cfg.include_kind_row
        csv_cfg.include_units_row = bool(cfg.results.include_units_row)
        csv_cfg.include_kind_row = bool(cfg.results.include_kind_row)
        try:
            return self._write_csv(path, keys, columns, specs, cfg)
        finally:
            csv_cfg.include_units_row = original_units
            csv_cfg.include_kind_row = original_kinds

    def _last_ut_ot_ut_output_path(self, cfg: PipelineConfig, csv_path: str | None) -> Path:
        configured = str(cfg.last_ut_ot_ut.path or "").strip()
        if configured:
            return self._resolve_pipeline_output(configured)
        if csv_path:
            base = Path(csv_path)
            return base.with_name(base.stem + "_last_ut_ot_ut.csv")
        return self._resolve_pipeline_output("csv/signals_last_ut_ot_ut.csv")

    def _build_last_ut_ot_ut_axis(self, t: np.ndarray, y: np.ndarray, cfg: PipelineConfig) -> tuple[np.ndarray, np.ndarray] | None:
        if getattr(self.bundle, "architecture", "classic") != "free_piston":
            return None
        fp = getattr(self.bundle, "free_piston", None)
        if fp is None or t.size < 5:
            return None
        step_deg = float(cfg.last_ut_ot_ut.step_deg or 0.0)
        axis_min_deg = float(cfg.last_ut_ot_ut.axis_min_deg)
        axis_max_deg = float(cfg.last_ut_ot_ut.axis_max_deg)
        if step_deg <= 0.0 or axis_max_deg <= axis_min_deg:
            return None
        x_idx = int(getattr(fp, "x_state_index", -1))
        v_idx = int(getattr(fp, "v_state_index", -1))
        y_arr = np.asarray(y, dtype=np.float64)
        if x_idx < 0 or v_idx < 0 or x_idx >= y_arr.shape[0] or v_idx >= y_arr.shape[0]:
            return None

        t_arr = np.asarray(t, dtype=np.float64)
        x_arr = np.asarray(y_arr[x_idx], dtype=np.float64)
        v_arr = np.asarray(y_arr[v_idx], dtype=np.float64)
        max_v = float(np.max(np.abs(v_arr))) if v_arr.size else 0.0
        eps = max(1.0e-10, 1.0e-6 * max_v)
        triplet = find_last_ut_ot_ut_turning_points(t_arr, x_arr, v_arr, eps=eps)
        if triplet is None:
            return None

        tp_ut0, tp_ot, tp_ut1 = triplet
        i0 = int(tp_ut0.sample_index)
        i1 = int(tp_ot.sample_index)
        i2 = int(tp_ut1.sample_index)
        if i2 - i0 < 2 or i1 <= i0 or i2 <= i1:
            return None

        x0 = float(x_arr[i0])
        x1 = float(x_arr[i1])
        x2 = float(x_arr[i2])
        dx01 = x0 - x1
        dx12 = x2 - x1
        if abs(dx01) <= 1.0e-15 or abs(dx12) <= 1.0e-15:
            return None

        theta_first = 180.0 * (x0 - x_arr[i0:i1 + 1]) / dx01
        theta_second = 180.0 + 180.0 * (x_arr[i1:i2 + 1] - x1) / dx12
        theta_first = np.maximum.accumulate(np.clip(theta_first, 0.0, 180.0))
        theta_second = np.maximum.accumulate(np.clip(theta_second, 180.0, 360.0))
        theta_seg = np.concatenate([theta_first[:-1], theta_second])
        t_seg = t_arr[i0:i2 + 1]
        theta_seg[0] = 0.0
        theta_seg[i1 - i0] = 180.0
        theta_seg[-1] = 360.0
        theta_seg = np.maximum.accumulate(theta_seg)

        theta_unique, unique_idx = np.unique(theta_seg, return_index=True)
        if theta_unique.size < 2:
            return None
        theta_targets = _grid_targets(0.0, 360.0, step_deg, include_endpoint=True)
        if theta_targets.size == 0:
            return None
        sample_t = np.interp(theta_targets, theta_unique, t_seg[unique_idx])
        axis_values = axis_min_deg + (axis_max_deg - axis_min_deg) * (theta_targets / 360.0)
        return sample_t, axis_values

    def _sample_last_ut_ot_ut_columns(
        self,
        cfg: PipelineConfig,
        *,
        keys: list[str],
        columns: dict[str, np.ndarray],
        t: np.ndarray,
        y: np.ndarray,
    ) -> dict[str, np.ndarray] | None:
        axis = self._build_last_ut_ot_ut_axis(t, y, cfg)
        if axis is None:
            return None
        sample_t, axis_values = axis
        t_source = np.asarray(columns.get("t_s", t), dtype=np.float64)
        sampled_columns: dict[str, np.ndarray] = {}
        axis_signal = str(cfg.last_ut_ot_ut.axis_signal or "")
        for key in keys:
            if key not in columns:
                continue
            values = np.asarray(columns[key])
            if key == axis_signal or key in ("theta_deg", "theta_local_deg"):
                sampled_columns[key] = axis_values
                continue
            if key == "cycle_index":
                sampled_columns[key] = np.rint(np.interp(sample_t, t_source, np.asarray(values, dtype=np.float64))).astype(np.int64)
                continue
            sampled_columns[key] = np.interp(sample_t, t_source, np.asarray(values, dtype=np.float64))
        return sampled_columns

    def _write_last_ut_ot_ut_csv(
        self,
        cfg: PipelineConfig,
        *,
        csv_path: str | None,
        keys: list[str],
        columns: dict[str, np.ndarray],
        specs: dict[str, SignalSpec],
        t: np.ndarray,
        y: np.ndarray,
    ) -> str | None:
        if not cfg.last_ut_ot_ut.enabled or not keys:
            return None
        sampled_columns = self._sample_last_ut_ot_ut_columns(cfg, keys=keys, columns=columns, t=t, y=y)
        if sampled_columns is None:
            ConsoleArtifactReporter.print_status("pipeline:csv:last-ut-ot-ut", "warn", reason="no-full-ut-ot-ut-cycle")
            return None
        return self._write_csv(self._last_ut_ot_ut_output_path(cfg, csv_path), keys, sampled_columns, specs, cfg)

    def _render_plots(
        self,
        cfg: PipelineConfig,
        *,
        layout_entries: list[tuple[PlotPipelineEntryConfig, Path]],
        columns: dict[str, np.ndarray],
        specs: dict[str, SignalSpec],
        t: np.ndarray,
        y: np.ndarray,
    ) -> tuple[list[str], list[str]]:
        del specs
        if not layout_entries:
            return [], []
        generated: list[str] = []
        used_layouts: list[str] = []
        for entry, layout_path in layout_entries:
            if not layout_path.exists():
                ConsoleArtifactReporter.print_status(layout_path.name, "warn", elapsed_s=0.0, reason="layout-missing")
                continue
            layout_keys = self._plot_layout_signal_keys(layout_path)
            row_keys = ["t_s", "cycle_index", "theta_deg", "theta_local_deg"]
            row_keys.extend(sorted(key for key in layout_keys if key not in row_keys))
            window = str(entry.window or "all").strip().lower()
            plot_columns = columns
            if window in {"last_ut_ot_ut", "last-complete-cycle", "last_complete_cycle"}:
                sampled = self._sample_last_ut_ot_ut_columns(cfg, keys=row_keys, columns=columns, t=t, y=y)
                if sampled is None:
                    ConsoleArtifactReporter.print_status(layout_path.name, "warn", elapsed_s=0.0, reason="no-full-ut-ot-ut-cycle")
                    continue
                plot_columns = sampled
            output_dir = self._plot_output_dir(cfg, window=window)
            rows = self._columns_to_rows(row_keys, plot_columns)
            if not rows:
                ConsoleArtifactReporter.print_skipped(layout_path.name, elapsed_s=0.0, reason="no-rows")
                continue
            prefix_parts = [self.config_path.stem]
            entry_prefix = str(entry.prefix or "").strip()
            if entry_prefix:
                prefix_parts.append(entry_prefix)
            prefix = "__".join(prefix_parts)
            ConsoleProgressReporter.print(f"Pipeline Plot: rendere {layout_path.name}")
            started = perf_counter()
            rendered_paths = render_plot_project(rows, layout_path, output_dir=output_dir, prefix=prefix, run_config_path=self.config_path)
            elapsed = perf_counter() - started
            generated.extend(rendered_paths)
            used_layouts.append(str(layout_path))
            ConsoleArtifactReporter.print_many_status(layout_path.name, rendered_paths, elapsed_s=elapsed)
        return generated, used_layouts

    def _write_summary(
        self,
        cfg: PipelineConfig,
        *,
        cfg_path: Path | None,
        raw_path: str | None,
        csv_path: str | None,
        columns: dict[str, np.ndarray],
        specs: dict[str, SignalSpec],
        markdown_columns: dict[str, np.ndarray] | None = None,
        t: np.ndarray,
        y: np.ndarray,
        cycle_indices: np.ndarray,
        mode: str,
    ) -> tuple[str | None, str | None, str | None]:
        if not cfg.summary.enabled:
            return None, None, None
        summary = _summary_dict(
            bundle=self.bundle,
            config_path=self.config_path,
            cfg_path=cfg_path,
            raw_path=raw_path,
            csv_path=csv_path,
            columns=columns,
            specs=specs,
            t=t,
            y=y,
            cycle_indices=cycle_indices,
            architecture=str(getattr(self.bundle, "architecture", "classic")),
            mode=mode,
        )
        text_target = self._resolve_pipeline_output(cfg.summary.text_path) if cfg.summary.text_path else None
        summary_path, summary_text_path = PipelineSummaryWriter.write(
            self._resolve_pipeline_output(cfg.summary.path),
            summary=summary,
            text_path=text_target,
        )
        markdown_out: str | None = None
        if cfg.summary.markdown_path:
            markdown_target = self._resolve_pipeline_output(cfg.summary.markdown_path)
            readme_columns = markdown_columns if markdown_columns is not None else columns
            rows = self._columns_to_rows(list(readme_columns.keys()), readme_columns)
            markdown_out = str(write_geometry_readme(self.bundle, markdown_target.parent, filename=markdown_target.name, rows=rows))
        return summary_path, summary_text_path, markdown_out

    def run(self, t: np.ndarray, y: np.ndarray, cycle_indices: np.ndarray) -> PipelineArtifacts:
        timings: dict[str, float] = {}
        total_started = perf_counter()
        cfg_path = self._pipeline_config_path()
        cfg = load_pipeline_config(cfg_path)
        ConsoleProgressReporter.print("Postprocessing pipeline: starte schlanke Ausgabeaufbereitung")
        plot_layout_entries = self._prepare_plot_layouts(cfg)
        plot_signal_keys: set[str] = set()
        for _entry, layout_path in plot_layout_entries:
            plot_signal_keys.update(self._plot_layout_signal_keys(layout_path))

        raw_path: str | None = None
        if cfg.raw.enabled:
            started = perf_counter()
            target = self._resolve_pipeline_output(cfg.raw.path)
            RawArchive.write(
                target,
                t=t,
                y=y,
                cycle_indices=cycle_indices,
                bundle=self.bundle,
                config_path=self.config_path,
                dtype=str(cfg.raw.dtype),
                compression=str(cfg.raw.compression),
            )
            timings["pipeline:raw"] = perf_counter() - started
            raw_path = str(target)
            ConsoleArtifactReporter.print_path_status("pipeline:raw", raw_path, elapsed_s=timings["pipeline:raw"])

        started = perf_counter()
        signal_started = started
        columns, specs = self._raw_columns(t, y, cycle_indices)
        selected = self._selected_keys(cfg)
        generation_selected = list(dict.fromkeys([*selected, *sorted(plot_signal_keys)]))
        include_kinds = {str(kind).strip() for kind in cfg.signals.include_kinds if str(kind).strip()}
        derivative_requested = self._needed_derivative_indices(generation_selected, include_kinds)
        self._add_derivative_columns(columns, specs, t, y, derivative_requested)
        if cfg.reconstruction.enabled:
            requested = self._needed_reconstructed_keys(generation_selected, include_kinds | {SIGNAL_RECONSTRUCTED})
            if cfg.reconstruction.only_selected:
                requested = {key for key in requested if key not in columns}
            self._add_reconstructed_columns(columns, specs, t, y, cycle_indices, requested)
        if cfg.integrals.enabled and SIGNAL_INTEGRAL in include_kinds:
            self._add_integral_columns(columns, specs, generation_selected, cfg)

        results_csv_path: str | None = None
        if cfg.results.enabled:
            started = perf_counter()
            result_keys = self._generated_result_keys(columns, selected)
            results_csv_path = self._write_results_csv(self._resolve_pipeline_output(cfg.results.path), result_keys, columns, specs, cfg)
            timings["pipeline:results"] = perf_counter() - started
            if results_csv_path:
                ConsoleArtifactReporter.print_path_status("pipeline:results", results_csv_path, elapsed_s=timings["pipeline:results"])

        keys, selected_columns, selected_specs = self._filter_selected_columns(columns, specs, selected, cfg)
        timings["pipeline:signals"] = perf_counter() - signal_started
        ConsoleTimingReporter.print("pipeline:signals", timings["pipeline:signals"], rows=int(t.shape[0]), signals=len(keys))

        csv_path: str | None = None
        if cfg.csv.enabled:
            started = perf_counter()
            csv_path = self._write_csv(self._resolve_pipeline_output(cfg.csv.path), keys, selected_columns, selected_specs, cfg)
            timings["pipeline:csv"] = perf_counter() - started
            if csv_path:
                ConsoleArtifactReporter.print_path_status("pipeline:csv", csv_path, elapsed_s=timings["pipeline:csv"])
            else:
                ConsoleArtifactReporter.print_status("pipeline:csv", "warn", elapsed_s=timings["pipeline:csv"], reason="no-signals")

        last_ut_ot_ut_csv_path: str | None = None
        if cfg.last_ut_ot_ut.enabled:
            started = perf_counter()
            last_ut_ot_ut_csv_path = self._write_last_ut_ot_ut_csv(
                cfg,
                csv_path=csv_path,
                keys=keys,
                columns=selected_columns,
                specs=selected_specs,
                t=t,
                y=y,
            )
            timings["pipeline:csv:last-ut-ot-ut"] = perf_counter() - started
            if last_ut_ot_ut_csv_path:
                ConsoleArtifactReporter.print_path_status("pipeline:csv:last-ut-ot-ut", last_ut_ot_ut_csv_path, elapsed_s=timings["pipeline:csv:last-ut-ot-ut"])

        summary_path: str | None = None
        summary_text_path: str | None = None
        summary_markdown_path: str | None = None
        if cfg.summary.enabled:
            started = perf_counter()
            summary_path, summary_text_path, summary_markdown_path = self._write_summary(
                cfg,
                cfg_path=cfg_path,
                raw_path=raw_path,
                csv_path=csv_path,
                columns=selected_columns,
                specs=selected_specs,
                markdown_columns=columns,
                t=t,
                y=y,
                cycle_indices=cycle_indices,
                mode="online",
            )
            timings["pipeline:summary"] = perf_counter() - started
            ConsoleArtifactReporter.print_path_status("pipeline:summary", summary_path, elapsed_s=timings["pipeline:summary"])
            if summary_markdown_path:
                ConsoleArtifactReporter.print_path_status("pipeline:summary:markdown", summary_markdown_path, elapsed_s=timings["pipeline:summary"])

        generated_plot_paths: list[str] = []
        plot_layout_paths: list[str] = []
        if plot_layout_entries:
            started = perf_counter()
            generated_plot_paths, plot_layout_paths = self._render_plots(
                cfg,
                layout_entries=plot_layout_entries,
                columns=columns,
                specs=specs,
                t=t,
                y=y,
            )
            timings["pipeline:plots"] = perf_counter() - started
            ConsoleTimingReporter.print("pipeline:plots", timings["pipeline:plots"], plots=len(generated_plot_paths))
        else:
            timings["pipeline:plots"] = 0.0

        timings["pipeline"] = perf_counter() - total_started
        ConsoleTimingReporter.print("pipeline", timings["pipeline"])
        return PipelineArtifacts(raw_archive_path=raw_path, csv_path=csv_path, results_csv_path=results_csv_path, last_ut_ot_ut_csv_path=last_ut_ot_ut_csv_path, summary_path=summary_path, summary_text_path=summary_text_path, summary_markdown_path=summary_markdown_path, generated_plot_paths=generated_plot_paths, plot_layout_paths=plot_layout_paths, signal_specs=selected_specs, timings=timings)


def run_pipeline_from_raw_archive(raw_path: str | Path, pipeline_config_path: str | Path | None = None, *, output_dir: str | Path | None = None) -> PipelineArtifacts:
    raw_archive_path = Path(raw_path).resolve()
    raw = RawArchive.read(raw_archive_path)
    cfg_path = Path(pipeline_config_path).resolve() if pipeline_config_path is not None else None
    cfg = load_pipeline_config(cfg_path)
    if not cfg.offline.enabled:
        raise ValueError("Offline-Reprocessing ist in der Pipeline-Config deaktiviert.")

    t = np.asarray(raw.get("t_s", np.zeros(0)), dtype=np.float64)
    y = np.asarray(raw.get("y", np.zeros((0, 0))), dtype=np.float64)
    cycle_indices = np.asarray(raw.get("cycle_index", np.zeros(t.shape[0])), dtype=np.int64)
    config_path_text = _scalar_npz_value(raw.get("config_path", "offline_raw_config.yaml")) or "offline_raw_config.yaml"
    config_path = Path(config_path_text)
    if not config_path.is_absolute():
        config_path = raw_archive_path.parent / config_path
    result_dir = Path(output_dir).resolve() if output_dir is not None else raw_archive_path.parent
    bundle = _offline_bundle_from_config_or_raw(raw, config_path, outdir=str(result_dir))
    service = PipelinePostprocessingService(bundle, config_path, result_dir=result_dir)
    timings: dict[str, float] = {}
    plot_layout_entries = service._prepare_plot_layouts(cfg)
    plot_signal_keys: set[str] = set()
    for _entry, layout_path in plot_layout_entries:
        plot_signal_keys.update(service._plot_layout_signal_keys(layout_path))

    columns, specs = service._raw_columns(t, y, cycle_indices)
    selected = service._selected_keys(cfg)
    generation_selected = list(dict.fromkeys([*selected, *sorted(plot_signal_keys)]))
    if not cfg.offline.allow_derivatives:
        cfg.signals.include_kinds = [kind for kind in cfg.signals.include_kinds if kind != SIGNAL_DERIVATIVE]
    if not cfg.offline.allow_reconstruction:
        cfg.signals.include_kinds = [kind for kind in cfg.signals.include_kinds if kind != SIGNAL_RECONSTRUCTED]
        cfg.reconstruction.enabled = False
    include_kinds = {str(kind).strip() for kind in cfg.signals.include_kinds if str(kind).strip()}
    derivative_requested = service._needed_derivative_indices(generation_selected, include_kinds)
    if derivative_requested:
        service._add_derivative_columns(columns, specs, t, y, derivative_requested)
    if cfg.reconstruction.enabled:
        requested = service._needed_reconstructed_keys(generation_selected, include_kinds | {SIGNAL_RECONSTRUCTED})
        if cfg.reconstruction.only_selected:
            requested = {key for key in requested if key not in columns}
        service._add_reconstructed_columns(columns, specs, t, y, cycle_indices, requested)
    if cfg.integrals.enabled and SIGNAL_INTEGRAL in include_kinds:
        service._add_integral_columns(columns, specs, generation_selected, cfg)

    results_csv_path: str | None = None
    if cfg.results.enabled:
        started = perf_counter()
        result_keys = service._generated_result_keys(columns, selected)
        results_csv_path = service._write_results_csv(service._resolve_pipeline_output(cfg.results.path), result_keys, columns, specs, cfg)
        timings["offline:results"] = perf_counter() - started

    keys, selected_columns, selected_specs = service._filter_selected_columns(columns, specs, selected, cfg)

    csv_path: str | None = None
    if cfg.csv.enabled:
        started = perf_counter()
        csv_path = service._write_csv(service._resolve_pipeline_output(cfg.csv.path), keys, selected_columns, selected_specs, cfg)
        timings["offline:csv"] = perf_counter() - started

    last_ut_ot_ut_csv_path: str | None = None
    if cfg.last_ut_ot_ut.enabled:
        started = perf_counter()
        last_ut_ot_ut_csv_path = service._write_last_ut_ot_ut_csv(
            cfg,
            csv_path=csv_path,
            keys=keys,
            columns=selected_columns,
            specs=selected_specs,
            t=t,
            y=y,
        )
        timings["offline:csv:last-ut-ot-ut"] = perf_counter() - started

    summary_path: str | None = None
    summary_text_path: str | None = None
    summary_markdown_path: str | None = None
    if cfg.summary.enabled:
        started = perf_counter()
        summary_path, summary_text_path, summary_markdown_path = service._write_summary(
            cfg,
            cfg_path=cfg_path,
            raw_path=str(raw_archive_path),
            csv_path=csv_path,
            columns=selected_columns,
            specs=selected_specs,
            markdown_columns=columns,
            t=t,
            y=y,
            cycle_indices=cycle_indices,
            mode="offline",
        )
        timings["offline:summary"] = perf_counter() - started

    generated_plot_paths: list[str] = []
    plot_layout_paths: list[str] = []
    if plot_layout_entries:
        started = perf_counter()
        generated_plot_paths, plot_layout_paths = service._render_plots(
            cfg,
            layout_entries=plot_layout_entries,
            columns=columns,
            specs=specs,
            t=t,
            y=y,
        )
        timings["offline:plots"] = perf_counter() - started

    return PipelineArtifacts(raw_archive_path=str(raw_archive_path), csv_path=csv_path, results_csv_path=results_csv_path, last_ut_ot_ut_csv_path=last_ut_ot_ut_csv_path, summary_path=summary_path, summary_text_path=summary_text_path, summary_markdown_path=summary_markdown_path, generated_plot_paths=generated_plot_paths, plot_layout_paths=plot_layout_paths, signal_specs=selected_specs, timings=timings)
