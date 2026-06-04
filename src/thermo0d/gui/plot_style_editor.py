from __future__ import annotations
import re
import copy
import csv
import json
import math
import os
import sys
import uuid
import yaml
from dataclasses import MISSING, asdict, dataclass, field, fields as dataclass_fields
from pathlib import Path
from typing import Any
from html import escape as html_escape
from collections import Counter

from thermo0d.config_versioning import (
    build_upgrade_message,
    config_schema_version_from_document,
    migrate_config_file_in_place,
    requires_version_upgrade,
)
from thermo0d.version import CURRENT_CONFIG_SCHEMA_VERSION
from thermo0d.app.paths import PathManager

from thermo0d.gui.dialogs import ask_question, exec_dialog, get_color, get_open_file_name, get_save_file_name, show_critical, show_warning, show_foreground

from PySide6.QtCore import QMimeData, QPoint, QSettings, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QBrush, QDrag, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QStatusBar,
    QStyle,
    QStyleFactory,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolBar,
    QToolButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QDoubleSpinBox,
    QHeaderView,
)

import matplotlib

matplotlib.use("QtAgg")
from matplotlib.figure import Figure
from matplotlib.ticker import MultipleLocator
from matplotlib import transforms as mtransforms
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar

from dataclasses import dataclass

from .signal_catalog import DEFAULT_SIGNAL_CATALOG_NAME, LEGACY_SIGNAL_CATALOG_NAMES


@dataclass
class _CompatPaths:
    project_dir: Path
    project_config_file: Path
    project_out_dir: Path


def find_code_root(start: Path | str) -> Path:
    cur = Path(start).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / 'src' / 'thermo0d').exists() and (candidate / 'Projekte').exists():
            return candidate
    return cur


def default_config_file(code_root: Path | str) -> Path:
    root = find_code_root(Path(code_root))
    for candidate in (root / 'Projekte' / 'config.yaml', root / 'Projekte' / 'config.yml', root / 'config.yaml', root / 'config.yml'):
        if candidate.exists():
            return candidate
    return root / 'Projekte' / 'config.yaml'


def build_paths(project_dir: Path | str):
    project_dir = Path(project_dir).resolve()
    return _CompatPaths(project_dir=project_dir, project_config_file=project_dir / 'config.yaml', project_out_dir=project_dir / 'results')

APP_ORG = "Meta GmbH"
APP_NAME = "Thermo0D PlotStyleEditor"
MIME_SIGNAL = "application/x-plotstyleeditor-signal"
MIME_SUBPLOT = "application/x-plotstyleeditor-subplot"
DEFAULT_SIGNALS_JSON = DEFAULT_SIGNAL_CATALOG_NAME
DEFAULT_PROJECT_YAML = "plot.yaml"
DEFAULT_CONFIG_JSON = "config.yaml"
ALLOWED_SIGNAL_FILE_BASENAMES = set(LEGACY_SIGNAL_CATALOG_NAMES)
TOP_LEVEL_SIGNAL_GROUPS = [
    ("minimal", "Minimal"),
    ("full", "Full"),
    ("full_only", "Full only"),
    ("postprocessed_dataframe_columns", "Postprocessed"),
    ("plotting_series_aliases", "Aliases"),
    ("default_plot_style_keys", "Defaults"),
]
SERIES_TYPES = ["line", "scatter", "step"]
PLOT_TYPES = ["line", "scatter", "step", "timing_cartesian", "timing_polar"]
LEGEND_POSITIONS = ["best", "upper right", "upper left", "lower right", "lower left", "upper center", "lower center"]
LINE_STYLES = ["-", "--", ":", "-."]
MARKERS = ["", "o", "s", "^", "v", "x", "+", "d"]
PRESETS = ["Light Engineering", "Compact Engineering", "Paper", "Dark Engineering", "Dark Presentation", "Presentation"]
AXIS_SIDES = ["left", "right"]
EVENT_TYPE_OPTIONS = ["custom", "reference", "valve", "combustion", "injection"]
EVENT_FILTER_OPTIONS = [
    ("all", "Alle Auto-Typen"),
    ("reference", "Nur Referenz (OT/UT)"),
    ("valve", "Nur Ventile"),
    ("combustion", "Nur Verbrennung"),
    ("injection", "Nur Einspritzung"),
    ("custom", "Nur Custom"),
]
DISPLAY_UNIT_PRESETS: dict[str, dict[str, float | str]] = {
    "raw": {"factor": 1.0, "offset": 0.0, "suffix": ""},
    "Pa": {"factor": 1.0, "offset": 0.0, "suffix": "Pa"},
    "bar": {"factor": 1.0e-5, "offset": 0.0, "suffix": "bar"},
    "MPa": {"factor": 1.0e-6, "offset": 0.0, "suffix": "MPa"},
    "K": {"factor": 1.0, "offset": 0.0, "suffix": "K"},
    "°C": {"factor": 1.0, "offset": -273.15, "suffix": "°C"},
    "m": {"factor": 1.0, "offset": 0.0, "suffix": "m"},
    "mm": {"factor": 1.0e3, "offset": 0.0, "suffix": "mm"},
    "m²": {"factor": 1.0, "offset": 0.0, "suffix": "m²"},
    "cm²": {"factor": 1.0e4, "offset": 0.0, "suffix": "cm²"},
    "mm²": {"factor": 1.0e6, "offset": 0.0, "suffix": "mm²"},
    "m³": {"factor": 1.0, "offset": 0.0, "suffix": "m³"},
    "cm³": {"factor": 1.0e6, "offset": 0.0, "suffix": "cm³"},
    "kg": {"factor": 1.0, "offset": 0.0, "suffix": "kg"},
    "g": {"factor": 1.0e3, "offset": 0.0, "suffix": "g"},
    "mg": {"factor": 1.0e6, "offset": 0.0, "suffix": "mg"},
    "J": {"factor": 1.0, "offset": 0.0, "suffix": "J"},
    "kJ": {"factor": 1.0e-3, "offset": 0.0, "suffix": "kJ"},
    "W": {"factor": 1.0, "offset": 0.0, "suffix": "W"},
    "kW": {"factor": 1.0e-3, "offset": 0.0, "suffix": "kW"},
    "deg": {"factor": 1.0, "offset": 0.0, "suffix": "deg"},
    "rad": {"factor": math.pi / 180.0, "offset": 0.0, "suffix": "rad"},
    "s": {"factor": 1.0, "offset": 0.0, "suffix": "s"},
    "ms": {"factor": 1.0e3, "offset": 0.0, "suffix": "ms"},
}
X_UNIT_PRESETS = ["raw", "deg", "rad", "s", "ms"]
SERIES_UNIT_PRESETS = list(DISPLAY_UNIT_PRESETS.keys())
X_LIMIT_MODES = ["data", "manual"]


def compact(value: float | int | str | None, digits: int = 6) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    v = float(value)
    if abs(v) < 1e-15:
        return "0"
    if abs(v) >= 1e6 or (0 < abs(v) < 1e-6):
        return f"{v:.6g}"
    return f"{v:.{digits}f}".rstrip("0").rstrip(".")


def new_id() -> str:
    return uuid.uuid4().hex[:12]


def _dataclass_from_mapping(model_cls: type, data: Any, *, aliases: dict[str, str] | None = None, defaults: dict[str, Any] | None = None):
    if isinstance(data, model_cls):
        return copy.deepcopy(data)
    if not isinstance(data, dict):
        return model_cls()
    aliases = aliases or {}
    defaults = defaults or {}
    field_map = {f.name: f for f in dataclass_fields(model_cls)}
    payload: dict[str, Any] = {}
    for key, value in dict(data).items():
        mapped = aliases.get(key, key)
        if mapped in field_map:
            payload[mapped] = value
    for key, value in defaults.items():
        payload.setdefault(key, value)
    for name, f in field_map.items():
        if name in payload:
            continue
        if f.default is not MISSING:
            payload[name] = f.default
        elif f.default_factory is not MISSING:  # type: ignore[attr-defined]
            payload[name] = f.default_factory()
    return model_cls(**payload)


def axis_model_from_data(data: Any) -> "AxisModel":
    payload = _dataclass_from_mapping(
        AxisModel,
        data,
        aliases={
            'tick_major_step': 'tick_step',
            'tick_minor_step': 'minor_tick_step',
            'grid_major': 'major_grid',
            'grid_minor': 'minor_grid',
        },
    )
    if getattr(payload, 'limit_mode', 'data') not in {'data', 'manual'}:
        payload.limit_mode = 'data'
    if payload.limit_mode == 'data' and ((payload.y_min != 0.0 or payload.y_max != 1.0) and (payload.tick_step > 0.0 or payload.minor_tick_step > 0.0)):
        # Backward-compatible heuristic for older saved projects that stored limits without an explicit mode.
        payload.limit_mode = 'manual'
    return payload


def series_model_from_data(data: Any) -> "SeriesModel":
    return _dataclass_from_mapping(SeriesModel, data, defaults={'unit_preset': 'raw'})


def event_model_from_data(data: Any) -> "EventModel":
    event = _dataclass_from_mapping(EventModel, data, defaults={'alpha': 0.9})
    try:
        event.alpha = float(event.alpha or 0.9)
    except Exception:
        event.alpha = 0.9
    return event


def horizontal_line_model_from_data(data: Any) -> "HorizontalLineModel":
    y_line = _dataclass_from_mapping(HorizontalLineModel, data, defaults={'alpha': 0.9})
    try:
        y_line.alpha = float(y_line.alpha or 0.9)
    except Exception:
        y_line.alpha = 0.9
    try:
        y_line.label_offset_pt = float(y_line.label_offset_pt or 0.0)
    except Exception:
        y_line.label_offset_pt = 3.0
    label_position = str(getattr(y_line, 'label_position', 'above') or 'above').strip().lower()
    if label_position not in {'above', 'below', 'center'}:
        label_position = 'above'
    y_line.label_position = label_position
    if label_position == 'above' and str(getattr(y_line, 'label_va', 'bottom') or 'bottom').strip().lower() == 'center':
        y_line.label_va = 'bottom'
    elif label_position == 'below' and str(getattr(y_line, 'label_va', 'bottom') or 'bottom').strip().lower() == 'center':
        y_line.label_va = 'top'
    elif label_position == 'center':
        y_line.label_va = 'center'
    return y_line


def style_model_from_data(data: Any) -> "StyleModel":
    return _dataclass_from_mapping(StyleModel, data)


def unit_preset(name: str) -> dict[str, float | str]:
    return DISPLAY_UNIT_PRESETS.get(name, DISPLAY_UNIT_PRESETS["raw"])


def transform_numeric_value(value: Any, unit_name: str = "raw", scale: float = 1.0, offset: float = 0.0) -> float | None:
    num = coerce_float(value)
    if num is None:
        return None
    preset = unit_preset(unit_name)
    return (num * float(preset["factor"]) + float(preset["offset"])) * scale + offset


def transform_values(values: list[Any] | None, unit_name: str = "raw", scale: float = 1.0, offset: float = 0.0) -> list[Any] | None:
    if values is None:
        return None
    return [transform_numeric_value(v, unit_name, scale, offset) for v in values]


def axis_title_with_unit(title: str, unit_name: str = "raw") -> str:
    text = str(title or "").strip()
    if "[" in text and "]" in text:
        return text
    suffix = str(unit_preset(unit_name).get("suffix", "") or "")
    if not suffix:
        return text
    return f"{text} [{suffix}]" if text else f"[{suffix}]"


class CompactDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDecimals(9)
        self.setKeyboardTracking(False)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def textFromValue(self, value: float) -> str:
        return compact(value, digits=9)

    def valueFromText(self, text: str) -> float:
        text = text.strip().replace(",", ".")
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            return self.value()


class ColorButton(QPushButton):
    colorChanged = Signal(str)

    def __init__(self, color: str = "#4472c4", text: str = "") -> None:
        super().__init__(text or color)
        self._color = color
        self.clicked.connect(self.pick)
        self.setMinimumWidth(90)
        self.refresh()

    def color(self) -> str:
        return self._color

    def setColor(self, color: str) -> None:
        if color and QColor(color).isValid():
            self._color = color
            self.refresh()
            self.colorChanged.emit(color)

    def refresh(self) -> None:
        fg = "#000000" if QColor(self._color).lightness() > 150 else "#ffffff"
        self.setText(self._color)
        self.setStyleSheet(
            f"QPushButton {{ background: {self._color}; color: {fg}; border: 1px solid #888; padding: 4px 8px; }}"
        )

    def pick(self) -> None:
        color = get_color(QColor(self._color), self, "Farbe wählen")
        if color.isValid():
            self.setColor(color.name())


@dataclass
class StyleModel:
    preset_name: str = "Light Engineering"
    background_color: str = "#ffffff"
    axes_facecolor: str = "#ffffff"
    text_color: str = "#202020"
    grid_color: str = "#d9d9d9"
    legend_facecolor: str = "#ffffff"
    legend_edgecolor: str = "#a0a0a0"
    default_line_width: float = 1.8
    default_marker_size: float = 4.5
    font_family: str = "DejaVu Sans"
    font_size: int = 10
    axis_label_size: int = 10
    tick_label_size: int = 10
    title_size: int = 12
    figure_title_size: int = 14
    subplot_title_visible: bool = True
    figure_title_visible: bool = True
    grid_visible: bool = True
    grid_alpha: float = 0.6
    legend_visible: bool = True
    legend_position: str = "best"
    tight_layout: bool = True

    @classmethod
    def preset(cls, name: str) -> "StyleModel":
        if name == "Compact Engineering":
            return cls(
                preset_name=name,
                background_color="#ffffff",
                axes_facecolor="#ffffff",
                text_color="#1f2937",
                grid_color="#d5dbe3",
                legend_facecolor="#ffffff",
                legend_edgecolor="#9aa4b2",
                default_line_width=1.7,
                default_marker_size=4.0,
                font_family="DejaVu Sans",
                font_size=9,
                axis_label_size=10,
                tick_label_size=9,
                title_size=11,
                figure_title_size=13,
                subplot_title_visible=True,
                figure_title_visible=True,
                grid_visible=True,
                grid_alpha=0.55,
                legend_visible=True,
                legend_position="best",
            )
        if name == "Paper":
            return cls(
                preset_name=name,
                background_color="#ffffff",
                axes_facecolor="#ffffff",
                text_color="#111827",
                grid_color="#e5e7eb",
                legend_facecolor="#ffffff",
                legend_edgecolor="#c7cdd4",
                default_line_width=1.6,
                default_marker_size=3.8,
                font_family="DejaVu Sans",
                font_size=9,
                axis_label_size=10,
                tick_label_size=9,
                title_size=11,
                figure_title_size=12,
                subplot_title_visible=False,
                figure_title_visible=False,
                grid_visible=True,
                grid_alpha=0.45,
                legend_visible=True,
                legend_position="best",
            )
        if name == "Dark Engineering":
            return cls(
                preset_name=name,
                background_color="#20242b",
                axes_facecolor="#20242b",
                text_color="#f0f3f7",
                grid_color="#4d5562",
                legend_facecolor="#2a3039",
                legend_edgecolor="#6b7280",
                default_line_width=1.9,
                default_marker_size=4.5,
                font_family="DejaVu Sans",
                font_size=10,
                axis_label_size=10,
                tick_label_size=10,
                title_size=12,
                figure_title_size=14,
                subplot_title_visible=True,
                figure_title_visible=True,
                grid_visible=True,
                grid_alpha=0.5,
                legend_visible=True,
                legend_position="best",
            )
        if name == "Dark Presentation":
            return cls(
                preset_name=name,
                background_color="#111827",
                axes_facecolor="#111827",
                text_color="#f9fafb",
                grid_color="#4b5563",
                legend_facecolor="#1f2937",
                legend_edgecolor="#6b7280",
                default_line_width=2.6,
                default_marker_size=6.0,
                font_family="DejaVu Sans",
                font_size=11,
                axis_label_size=12,
                tick_label_size=11,
                title_size=15,
                figure_title_size=17,
                subplot_title_visible=True,
                figure_title_visible=True,
                grid_visible=True,
                grid_alpha=0.45,
                legend_visible=True,
                legend_position="best",
            )
        if name == "Presentation":
            return cls(
                preset_name=name,
                background_color="#ffffff",
                axes_facecolor="#ffffff",
                text_color="#111111",
                grid_color="#c7d1dd",
                legend_facecolor="#ffffff",
                legend_edgecolor="#8a94a3",
                default_line_width=2.4,
                default_marker_size=6.0,
                font_family="DejaVu Sans",
                font_size=11,
                axis_label_size=12,
                tick_label_size=11,
                title_size=15,
                figure_title_size=17,
                subplot_title_visible=True,
                figure_title_visible=True,
                grid_visible=True,
                grid_alpha=0.6,
                legend_visible=True,
                legend_position="best",
            )
        return cls(
            preset_name="Light Engineering",
            background_color="#ffffff",
            axes_facecolor="#ffffff",
            text_color="#202020",
            grid_color="#d8d8d8",
            legend_facecolor="#ffffff",
            legend_edgecolor="#9aa0a6",
            default_line_width=1.8,
            default_marker_size=4.5,
            font_family="DejaVu Sans",
            font_size=10,
            axis_label_size=10,
            tick_label_size=10,
            title_size=12,
            figure_title_size=14,
            subplot_title_visible=True,
            figure_title_visible=True,
            grid_visible=True,
            grid_alpha=0.65,
            legend_visible=True,
            legend_position="best",
        )


@dataclass
class AxisModel:
    id: str = field(default_factory=new_id)
    title: str = ""
    side: str = "left"
    spine_offset: float = 0.0
    color: str = "#1f77b4"
    visible: bool = True
    # Manual Y-axis control for the plot inspector and persisted project files.
    limit_mode: str = "data"
    y_min: float = 0.0
    y_max: float = 1.0
    tick_step: float = 0.0
    minor_tick_step: float = 0.0
    major_grid: bool = True
    minor_grid: bool = False


@dataclass
class SeriesModel:
    id: str = field(default_factory=new_id)
    signal_key: str = "p_cyl_pa"
    label: str = ""
    axis_id: str = ""
    visible: bool = True
    color: str = "#1f77b4"
    line_style: str = "-"
    marker: str = ""
    line_width: float = 1.8
    marker_size: float = 4.5
    unit_preset: str = "raw"
    scale_factor: float = 1.0
    offset: float = 0.0
    series_type: str = "line"




@dataclass
class HorizontalLineModel:
    id: str = field(default_factory=new_id)
    y: float = 0.0
    axis_id: str = ""
    label: str = ""
    color: str = "#667085"
    line_style: str = "--"
    line_width: float = 1.0
    alpha: float = 0.9
    visible: bool = True
    show_label: bool = True
    label_x: float = 0.99
    label_position: str = "above"
    label_offset_pt: float = 3.0
    label_ha: str = "right"
    label_va: str = "bottom"
    label_font_size: float = 8.0
    label_bg_color: str = "#ffffff"
    label_bg_alpha: float = 0.75
    label_border_color: str = "none"


@dataclass
class EventModel:
    id: str = field(default_factory=new_id)
    x: float = 0.0
    label: str = "Event"
    color: str = "#666666"
    line_style: str = ":"
    line_width: float = 1.0
    alpha: float = 0.9
    visible: bool = True
    show_label: bool = True
    source: str = "manual"
    source_note: str = ""
    locked: bool = False
    event_type: str = "custom"
    label_rotation: float = 90.0
    label_font_size: float = 7.0
    label_bg_color: str = "#ffffff"
    label_bg_alpha: float = 0.8
    label_border_color: str = "none"
    label_y: float = 0.98
    label_ha: str = "right"
    label_va: str = "top"


@dataclass
class SubplotModel:
    id: str = field(default_factory=new_id)
    title: str = "Subplot"
    show_title: bool = True
    plot_type: str = "line"
    x_signal: str = "theta_deg"
    x_title: str = "Theta"
    x_unit_preset: str = "deg"
    x_scale_factor: float = 1.0
    x_offset: float = 0.0
    x_limit_mode: str = "data"
    x_min: float = 0.0
    x_max: float = 720.0
    x_start_at_zero: bool = True
    y_axes: list[AxisModel] = field(default_factory=lambda: [AxisModel(title="Y", side="left", color="#1f77b4")])
    series: list[SeriesModel] = field(default_factory=list)
    events: list[EventModel] = field(default_factory=list)
    y_lines: list[HorizontalLineModel] = field(default_factory=list)
    text_box: dict[str, Any] = field(default_factory=dict)
    info_box: dict[str, Any] = field(default_factory=dict)
    legend_visible: bool = True
    legend_position: str = "best"
    show_grid: bool = True


@dataclass
class FigureModel:
    id: str = field(default_factory=new_id)
    title: str = "Figure 1"
    rows: int = 1
    cols: int = 1
    subplots: list[SubplotModel] = field(default_factory=lambda: [SubplotModel()])


@dataclass
class ProjectModel:
    name: str = "Untitled Project"
    figures: list[FigureModel] = field(default_factory=lambda: [FigureModel()])
    style: StyleModel = field(default_factory=lambda: StyleModel.preset("Light Engineering"))
    style_sheet: str = ""
    config_path: str = ""
    signals_path: str = ""
    preview_csv_path: str = ""
    selected_cylinder: str = "user_cylinder_1"
    notes: str = ""


@dataclass
class PreviewSeriesTarget:
    artist: Any
    subplot_index: int
    series_id: str
    label: str
    color: str
    x_values: list[float]
    y_values: list[float]


class CsvPreviewData:
    def __init__(self) -> None:
        self.path = ""
        self.headers: list[str] = []
        self.rows: list[dict[str, Any]] = []
        self.available_set: set[str] = set()
        self.error = ""

    def load(self, path: str) -> None:
        self.path = path
        self.headers = []
        self.rows = []
        self.available_set = set()
        self.error = ""
        if not path:
            return
        p = Path(path)
        if not p.exists():
            self.error = "Datei nicht gefunden."
            return

        def _read_with_delimiter(delimiter: str) -> tuple[list[str], list[dict[str, Any]]]:
            out_headers: list[str] = []
            out_rows: list[dict[str, Any]] = []
            with p.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle, delimiter=delimiter)
                out_headers = [str(h).strip() for h in (reader.fieldnames or []) if h is not None]
                for index, row in enumerate(reader):
                    if row is None:
                        continue
                    clean: dict[str, Any] = {}
                    for key, value in row.items():
                        if key is None:
                            continue
                        clean[str(key).strip()] = self._parse_value(value)
                    out_rows.append(clean)
                    if index >= 2999:
                        break
            return out_headers, out_rows

        try:
            sample = p.read_text(encoding="utf-8-sig", errors="ignore")[:4096]
            candidate_delimiters: list[str] = []
            try:
                sniffed = csv.Sniffer().sniff(sample, delimiters=",;\t")
                candidate_delimiters.append(sniffed.delimiter)
            except Exception:
                pass

            counts = {
                ";": sample.count(";"),
                ",": sample.count(","),
                "\t": sample.count("\t"),
            }
            ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
            for delim, count in ranked:
                if count > 0 and delim not in candidate_delimiters:
                    candidate_delimiters.append(delim)
            if not candidate_delimiters:
                candidate_delimiters = [";", ",", "\t"]

            best_headers: list[str] = []
            best_rows: list[dict[str, Any]] = []
            for delim in candidate_delimiters:
                headers, rows = _read_with_delimiter(delim)
                if len(headers) > len(best_headers):
                    best_headers, best_rows = headers, rows
                if len(headers) > 1:
                    break

            self.headers = best_headers
            self.rows = best_rows

            if len(self.headers) <= 1 and self.headers and any(sep in self.headers[0] for sep in [";", ",", "\t"]):
                for delim in [";", ",", "\t"]:
                    headers, rows = _read_with_delimiter(delim)
                    if len(headers) > len(self.headers):
                        self.headers = headers
                        self.rows = rows
        except Exception as exc:
            self.error = str(exc)
            return

        self.available_set = {h for h in self.headers if h}

    @staticmethod
    def _parse_value(value: Any) -> Any:
        if value is None:
            return None
        text = str(value).strip()
        if text == "":
            return None
        text2 = text.replace(",", ".")
        try:
            return float(text2)
        except Exception:
            return text


class SignalCatalog:
    def __init__(self) -> None:
        self.path = ""
        self.raw: dict[str, list[str]] = {}
        self.metadata: dict[str, dict[str, Any]] = {}
        self.error = ""
        self.available_set: set[str] = set()
        self.selected_cylinder = "user_cylinder_1"

    def load(self, path: str) -> None:
        self.path = path
        self.raw = {}
        self.error = ""
        if not path:
            return
        p = Path(path)
        if not p.exists():
            self.error = "Datei nicht gefunden."
            return
        try:
            with p.open("r", encoding="utf-8") as handle:
                if p.suffix.lower() in {".yaml", ".yml"}:
                    data = yaml.safe_load(handle) or {}
                else:
                    data = json.load(handle)
            out: dict[str, list[str]] = {}
            for key, value in data.items():
                if isinstance(value, list):
                    out[key] = [str(v) for v in value]
            self.raw = out
            meta = data.get("signal_metadata") if isinstance(data.get("signal_metadata"), dict) else {}
            self.metadata = {str(k): dict(v) for k, v in meta.items() if isinstance(v, dict)}
        except Exception as exc:
            self.error = str(exc)
            self.raw = {}
            self.metadata = {}

    def groups(self) -> list[tuple[str, str]]:
        return [(k, label) for k, label in TOP_LEVEL_SIGNAL_GROUPS if k in self.raw]

    def resolve(self, signal_key: str, cylinder_name: str | None = None) -> str:
        cylinder = cylinder_name or self.selected_cylinder or "user_cylinder_1"
        return signal_key.replace("<cyl>", cylinder)

    def heuristic_category(self, signal: str) -> str:
        s = signal.lower()
        if "theta" in s or "crank" in s or s.startswith("t_") or s.endswith("_deg"):
            return "Timing"
        if "p_" in s or s.startswith("p") or s.endswith("_pa") or s.endswith("_bar") or "pressure" in s:
            return "Pressure"
        if "t_" in s or s.endswith("_k") or "temp" in s:
            return "Temperature"
        if "mdot" in s or "flow" in s:
            return "Mass flow"
        if re_any(s, ["m_", "mass", "fuel", "co2", "h2o", "o2", "n2"]):
            return "Mass & species"
        if re_any(s, ["qdot", "dq_", "u_", "hdot", "energy", "combustion", "evap"]):
            return "Energy & combustion"
        if re_any(s, ["a_", "area", "v_", "lift", "x_", "geom", "volume", "piston"]):
            return "Geometry"
        if re_any(s, ["lambda", "alpha", "kappa", "gamma", "cp", "cv", "state", "phase", "fraction"]):
            return "State & coefficients"
        return "Other"

    def items_for_tree(self) -> dict[str, dict[str, list[str]]]:
        tree: dict[str, dict[str, list[str]]] = {}
        for key, label in self.groups():
            bucket: dict[str, list[str]] = {}
            for signal in self.raw.get(key, []):
                cat = self.heuristic_category(signal)
                bucket.setdefault(cat, []).append(signal)
            for values in bucket.values():
                values.sort(key=str.lower)
            tree[label] = dict(sorted(bucket.items(), key=lambda item: item[0].lower()))
        return tree

    def derived_alias_candidates(self, signal: str) -> list[str]:
        resolved = self.resolve(signal)
        mapping = {
            "A_ex_mm2": ["A_ex", "valves__A_ex_eff_m2", resolved.replace("_mm2", "_m2")],
            "A_in_mm2": ["A_in", "valves__A_in_eff_m2", resolved.replace("_mm2", "_m2")],
            "V_cm3": ["V_m3", "V", resolved.replace("_cm3", "_m3")],
            "p_cyl_bar": ["p_cyl_pa", "p", resolved.replace("_bar", "_pa")],
            "p_ref_compression_bar": ["p_ref_compression_pa"],
            "p_ref_expansion_bar": ["p_ref_expansion_pa"],
        }
        return [c for c in mapping.get(signal, []) if c]

    def find_available_signal(self, signal: str, available_headers: set[str], cylinder_name: str) -> tuple[str | None, str]:
        exact = self.resolve(signal, cylinder_name)
        if exact in available_headers:
            return exact, "exact"
        low_map = {h.lower(): h for h in available_headers}
        if exact.lower() in low_map:
            return low_map[exact.lower()], "case-insensitive"
        for candidate in self.derived_alias_candidates(signal):
            if candidate in available_headers:
                return candidate, "alias"
            if candidate.lower() in low_map:
                return low_map[candidate.lower()], "alias"

        def normalize(name: str) -> str:
            out = name.lower().strip()
            out = re.sub(r"user_cylinder_\d+", "<cyl>", out)
            out = re.sub(r"cylinder_\d+", "<cyl>", out)
            out = re.sub(r"cyl_?\d+", "<cyl>", out)
            out = re.sub(r"__+", "__", out)
            return out

        normalized_exact = normalize(exact)
        normalized_signal = normalize(signal)
        normalized_map: dict[str, list[str]] = {}
        for header in available_headers:
            normalized_map.setdefault(normalize(header), []).append(header)

        for key in (normalized_exact, normalized_signal):
            matches = normalized_map.get(key, [])
            if len(matches) == 1:
                return matches[0], "normalized"

        suffix = exact.split("__", 1)[-1] if "__" in exact else exact
        matches = [h for h in available_headers if h.endswith(suffix)]
        if len(matches) == 1:
            return matches[0], "suffix"

        signal_suffix = signal.split("__", 1)[-1] if "__" in signal else signal
        matches2 = [h for h in available_headers if h.lower().endswith(signal_suffix.lower())]
        if len(matches2) == 1:
            return matches2[0], "suffix"

        norm_suffix = normalized_exact.split("__", 1)[-1] if "__" in normalized_exact else normalized_exact
        matches3 = [h for h in available_headers if normalize(h).endswith(norm_suffix)]
        if len(matches3) == 1:
            return matches3[0], "normalized-suffix"
        return None, "missing"

    def derived_data(self, signal: str, source: dict[str, list[Any]]) -> list[Any] | None:
        if signal == "A_ex_mm2":
            base = source.get("A_ex") or source.get("valves__A_ex_eff_m2")
            return scale_values(base, 1e6) if base is not None else None
        if signal == "A_in_mm2":
            base = source.get("A_in") or source.get("valves__A_in_eff_m2")
            return scale_values(base, 1e6) if base is not None else None
        if signal == "V_cm3":
            base = source.get("V_m3") or source.get("V")
            return scale_values(base, 1e6) if base is not None else None
        if signal == "p_cyl_bar":
            base = source.get("p_cyl_pa") or source.get("p")
            return scale_values(base, 1e-5) if base is not None else None
        if signal == "p_ref_compression_bar":
            base = source.get("p_ref_compression_pa")
            return scale_values(base, 1e-5) if base is not None else None
        if signal == "p_ref_expansion_bar":
            base = source.get("p_ref_expansion_pa")
            return scale_values(base, 1e-5) if base is not None else None
        return None


class SignalTreeWidget(QTreeWidget):
    signalDropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["Signal", "Status"])
        self.setColumnCount(2)
        self.setAlternatingRowColors(True)
        self.setSelectionMode(QTreeWidget.SingleSelection)
        self.setDragEnabled(True)
        self.setUniformRowHeights(True)

    def startDrag(self, supportedActions: Qt.DropActions) -> None:
        item = self.currentItem()
        if item is None:
            return
        signal_key = item.data(0, Qt.UserRole)
        if not signal_key:
            return
        mime = QMimeData()
        mime.setData(MIME_SIGNAL, str(signal_key).encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(supportedActions)


class SeriesListWidget(QListWidget):
    signalDropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.NoDragDrop)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setAlternatingRowColors(True)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_SIGNAL):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_SIGNAL):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_SIGNAL):
            signal = bytes(event.mimeData().data(MIME_SIGNAL)).decode("utf-8")
            self.signalDropped.emit(signal)
            event.acceptProposedAction()
            return
        super().dropEvent(event)


class FigureListWidget(QListWidget):
    subplotDropped = Signal(int, str, int, bool)
    dragFeedback = Signal(str)
    targetFigureChanged = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DropOnly)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setAlternatingRowColors(True)
        self._drag_target_row: int | None = None

    def _event_point(self, event) -> QPoint:
        if hasattr(event, 'position'):
            try:
                return event.position().toPoint()
            except Exception:
                pass
        return event.pos()

    def _set_drag_target_row(self, row: int | None) -> None:
        if row is not None and row < 0:
            row = None
        if row == self._drag_target_row:
            return
        self._drag_target_row = row
        self.targetFigureChanged.emit(row)

    def _copy_mode(self) -> bool:
        return bool(QApplication.keyboardModifiers() & Qt.ControlModifier)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_SUBPLOT):
            event.acceptProposedAction()
            self.dragFeedback.emit('Subplot auf Ziel-Figure ziehen – Strg = kopieren, ohne Strg = verschieben')
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_SUBPLOT):
            row = self.indexAt(self._event_point(event)).row()
            self._set_drag_target_row(row if row >= 0 else None)
            copy_mode = self._copy_mode()
            event.setDropAction(Qt.CopyAction if copy_mode else Qt.MoveAction)
            if row >= 0:
                action = 'kopieren' if copy_mode else 'verschieben'
                item = self.item(row)
                target_text = item.text() if item is not None else f'Figure {row + 1}'
                self.dragFeedback.emit(f'Subplot hierhin {action}: {target_text}')
                event.accept()
            else:
                self.dragFeedback.emit('Subplot auf eine Figure in der linken Liste ziehen')
                event.ignore()
            return
        super().dragMoveEvent(event)

    def dragLeaveEvent(self, event) -> None:
        self._set_drag_target_row(None)
        self.dragFeedback.emit('')
        super().dragLeaveEvent(event)

    def dropEvent(self, event) -> None:
        if event.mimeData().hasFormat(MIME_SUBPLOT):
            row = self.indexAt(self._event_point(event)).row()
            payload_raw = bytes(event.mimeData().data(MIME_SUBPLOT)).decode('utf-8')
            try:
                payload = json.loads(payload_raw)
            except Exception:
                payload = {}
            src_fig = int(payload.get('source_figure_index', -1))
            subplot_id = str(payload.get('subplot_id', '') or '')
            copy_mode = self._copy_mode()
            self._set_drag_target_row(None)
            self.dragFeedback.emit('')
            if row >= 0 and subplot_id:
                event.setDropAction(Qt.CopyAction if copy_mode else Qt.MoveAction)
                self.subplotDropped.emit(src_fig, subplot_id, row, copy_mode)
                event.accept()
            else:
                event.ignore()
            return
        super().dropEvent(event)


class SubplotListWidget(QListWidget):
    dragFeedback = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.DragOnly)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setAlternatingRowColors(True)

    def startDrag(self, supportedActions: Qt.DropActions) -> None:
        item = self.currentItem()
        if item is None:
            return
        subplot_id = str(item.data(Qt.UserRole) or '')
        source_figure_index = int(item.data(Qt.UserRole + 1) or -1)
        if not subplot_id or source_figure_index < 0:
            return
        mime = QMimeData()
        mime.setData(MIME_SUBPLOT, json.dumps({
            'subplot_id': subplot_id,
            'source_figure_index': source_figure_index,
        }).encode('utf-8'))
        drag = QDrag(self)
        drag.setMimeData(mime)
        try:
            pixmap = self.viewport().grab(self.visualItemRect(item))
            if not pixmap.isNull():
                drag.setPixmap(pixmap)
                drag.setHotSpot(QPoint(min(24, max(0, pixmap.width() // 4)), min(12, max(0, pixmap.height() // 2))))
        except Exception:
            pass
        self.dragFeedback.emit(f"Ziehe Subplot '{item.text()}' auf eine Figure – Strg = kopieren")
        drag.exec(Qt.CopyAction | Qt.MoveAction, Qt.MoveAction)
        self.dragFeedback.emit('')


class MatplotlibPreview(QWidget):
    seriesDoubleClicked = Signal(int, str)
    seriesMoveRequested = Signal(int, str, int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        

        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.figure = Figure(constrained_layout=True)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas, 1)

        self.hover_info = QTextEdit()
        self.hover_info.setReadOnly(True)
        self.hover_info.setMaximumHeight(120)
        self.hover_info.setMinimumHeight(72)
        self.hover_info.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.hover_info.setHtml(self._default_hover_html())
        layout.addWidget(self.hover_info)

        self._axes_to_subplot: dict[Any, int] = {}
        self._artist_targets: list[PreviewSeriesTarget] = []
        self._subplot_targets: dict[int, list[PreviewSeriesTarget]] = {}
        self._drag_state: dict[str, Any] | None = None
        self._drag_threshold = 6
        self._last_hover_signature: tuple | None = None
        self.canvas.mpl_connect("button_press_event", self._on_button_press)
        self.canvas.mpl_connect("motion_notify_event", self._on_motion_notify)
        self.canvas.mpl_connect("button_release_event", self._on_button_release)
        self.canvas.mpl_connect("figure_leave_event", self._on_figure_leave)

    def _default_hover_html(self) -> str:
        return "<span style='color:#666666'>Hover over a series to inspect X and Y values.</span>"

    def set_interaction_targets(self, axes_to_subplot: dict[Any, int], artist_targets: list[PreviewSeriesTarget]) -> None:
        self._axes_to_subplot = dict(axes_to_subplot)
        self._artist_targets = list(artist_targets)
        self._subplot_targets = {}
        for target in self._artist_targets:
            self._subplot_targets.setdefault(int(target.subplot_index), []).append(target)
        self._drag_state = None
        self._set_hover_html(self._default_hover_html(), signature=("default", len(self._artist_targets)))

    def clear_interaction_targets(self) -> None:
        self._axes_to_subplot.clear()
        self._artist_targets.clear()
        self._subplot_targets.clear()
        self._drag_state = None
        self._set_hover_html(self._default_hover_html(), signature=("default", 0))

    def _set_hover_html(self, html: str, signature: tuple | None = None) -> None:
        if signature is not None and signature == self._last_hover_signature:
            return
        self.hover_info.setHtml(html)
        self._last_hover_signature = signature

    def _find_hit_series(self, event) -> tuple[PreviewSeriesTarget, dict[str, Any]] | None:
        for target in reversed(self._artist_targets):
            try:
                hit, details = target.artist.contains(event)
            except Exception:
                hit, details = False, {}
            if hit:
                return target, (details or {})
        return None

    def _subplot_from_axes(self, axes_obj: Any) -> int | None:
        if axes_obj is None:
            return None
        return self._axes_to_subplot.get(axes_obj)

    def _format_hover_value(self, value: float | None) -> str:
        return compact(value, digits=6) if value is not None else "-"

    def _extract_anchor(self, event, target: PreviewSeriesTarget, details: dict[str, Any]) -> tuple[int | None, float | None]:
        indices = details.get("ind") if isinstance(details, dict) else None
        if isinstance(indices, (list, tuple)) and indices:
            try:
                idx = int(indices[0])
                if 0 <= idx < len(target.x_values):
                    return idx, float(target.x_values[idx])
            except Exception:
                pass
        x_event = getattr(event, "xdata", None)
        if x_event is None or not target.x_values:
            return None, None
        try:
            anchor_x = float(x_event)
            idx = min(range(len(target.x_values)), key=lambda i: abs(float(target.x_values[i]) - anchor_x))
            return idx, float(target.x_values[idx])
        except Exception:
            return None, None

    def _nearest_index(self, values: list[float], anchor_x: float | None) -> int | None:
        if not values or anchor_x is None:
            return None
        try:
            return min(range(len(values)), key=lambda i: abs(float(values[i]) - float(anchor_x)))
        except Exception:
            return None

    def _build_hover_html(self, hovered: PreviewSeriesTarget, event, details: dict[str, Any]) -> tuple[str, tuple]:
        idx, anchor_x = self._extract_anchor(event, hovered, details)
        if idx is None or anchor_x is None:
            return self._default_hover_html(), ("default", len(self._artist_targets))

        signature_parts: list[Any] = ["hover", int(hovered.subplot_index), str(hovered.series_id), round(float(anchor_x), 9)]
        lines = [
            "<div style='font-family:Consolas, &quot;DejaVu Sans Mono&quot;, monospace; font-size:11px;'>",
            f"<div><b>X</b>: {html_escape(self._format_hover_value(anchor_x))}</div>",
        ]
        for target in self._subplot_targets.get(int(hovered.subplot_index), []):
            local_idx = self._nearest_index(target.x_values, anchor_x)
            y_value = None
            x_value = None
            if local_idx is not None and 0 <= local_idx < len(target.y_values):
                y_value = target.y_values[local_idx]
                x_value = target.x_values[local_idx] if local_idx < len(target.x_values) else anchor_x
            signature_parts.extend([str(target.series_id), self._format_hover_value(y_value)])
            label = html_escape(target.label or target.series_id)
            value_html = html_escape(self._format_hover_value(y_value))
            x_local_html = html_escape(self._format_hover_value(x_value if x_value is not None else anchor_x))
            weight = "700" if target.series_id == hovered.series_id else "400"
            color = target.color or "#1f77b4"
            lines.append(
                f"<div><span style='color:{color};font-weight:{weight}'>{label}</span>: "
                f"<span style='color:{color};font-weight:{weight}'>{value_html}</span> "
                f"<span style='color:#666666'>(x={x_local_html})</span></div>"
            )
        lines.append("</div>")
        return "".join(lines), tuple(signature_parts)

    def _update_hover_info(self, event) -> None:
        hit = self._find_hit_series(event)
        if hit is None:
            self._set_hover_html(self._default_hover_html(), signature=("default", len(self._artist_targets)))
            return
        target, details = hit
        html, signature = self._build_hover_html(target, event, details)
        self._set_hover_html(html, signature=signature)

    def _on_figure_leave(self, _event) -> None:
        self._set_hover_html(self._default_hover_html(), signature=("default", len(self._artist_targets)))

    def _subplot_series_targets(self, subplot_index: int | None) -> list[PreviewSeriesTarget]:
        if subplot_index is None:
            return []
        return list(self._subplot_targets.get(int(subplot_index), []))

    def _open_series_data_dialog(self, subplot_index: int | None) -> None:
        targets = self._subplot_series_targets(subplot_index)
        if not targets:
            return
        dialog = PreviewSeriesDataDialog(self, int(subplot_index), targets)
        exec_dialog(dialog)

    def _show_context_menu(self, event, subplot_index: int | None) -> None:
        targets = self._subplot_series_targets(subplot_index)
        if not targets:
            return
        menu = QMenu(self)
        action_show_data = menu.addAction("Daten anzeigen")
        try:
            global_pos = self.canvas.mapToGlobal(QPoint(int(getattr(event, "x", 0) or 0), int(getattr(event, "y", 0) or 0)))
        except Exception:
            global_pos = self.mapToGlobal(QPoint(0, 0))
        chosen = menu.exec(global_pos)
        if chosen is action_show_data:
            self._open_series_data_dialog(subplot_index)

    def _on_button_press(self, event) -> None:
        button = getattr(event, "button", None)
        hit = self._find_hit_series(event)
        if button == 3:
            self._drag_state = None
            subplot_index = None
            if hit is not None:
                subplot_index = int(hit[0].subplot_index)
            else:
                subplot_index = self._subplot_from_axes(getattr(event, "inaxes", None))
            self._show_context_menu(event, subplot_index)
            return
        if button != 1:
            self._drag_state = None
            return
        if hit is None:
            self._drag_state = None
            return
        target, _details = hit
        subplot_index, series_id = target.subplot_index, target.series_id
        if getattr(event, "dblclick", False):
            self._drag_state = None
            self.seriesDoubleClicked.emit(subplot_index, series_id)
            return
        self._drag_state = {
            "src_subplot": subplot_index,
            "series_id": series_id,
            "press_x": float(getattr(event, "x", 0.0) or 0.0),
            "press_y": float(getattr(event, "y", 0.0) or 0.0),
            "dragging": False,
        }

    def _on_motion_notify(self, event) -> None:
        self._update_hover_info(event)
        if not self._drag_state:
            return
        dx = abs(float(getattr(event, "x", 0.0) or 0.0) - self._drag_state["press_x"])
        dy = abs(float(getattr(event, "y", 0.0) or 0.0) - self._drag_state["press_y"])
        if dx >= self._drag_threshold or dy >= self._drag_threshold:
            self._drag_state["dragging"] = True

    def _on_button_release(self, event) -> None:
        if not self._drag_state:
            return
        state = self._drag_state
        self._drag_state = None
        if not state.get("dragging"):
            return
        dest_subplot = self._subplot_from_axes(getattr(event, "inaxes", None))
        src_subplot = int(state["src_subplot"])
        if dest_subplot is None or dest_subplot == src_subplot:
            return
        self.seriesMoveRequested.emit(src_subplot, str(state["series_id"]), dest_subplot)

    def refresh(self) -> None:
        self.canvas.draw_idle()


class PreviewSeriesDataDialog(QDialog):
    def __init__(self, parent: QWidget | None, subplot_index: int, targets: list[PreviewSeriesTarget]) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle(f"Daten anzeigen – Subplot {subplot_index + 1}")
        self.resize(980, 640)

        root = QVBoxLayout(self)
        title = QLabel(f"Seriendaten im Subplot {subplot_index + 1}")
        title.setStyleSheet("font-weight:600;")
        root.addWidget(title)

        self.table = QTableWidget(self)
        self.table.setAlternatingRowColors(True)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setSelectionMode(QTableWidget.ExtendedSelection)
        self.table.setSortingEnabled(False)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setStretchLastSection(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        root.addWidget(self.table, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.button(QDialogButtonBox.Close).clicked.connect(self.close)
        root.addWidget(buttons)

        self._populate_table(targets)

    def _populate_table(self, targets: list[PreviewSeriesTarget]) -> None:
        clean_targets = [t for t in targets if t is not None]
        if not clean_targets:
            self.table.setColumnCount(0)
            self.table.setRowCount(0)
            return

        row_count = max((max(len(t.x_values), len(t.y_values)) for t in clean_targets), default=0)
        headers = ["Index", "X"] + [str(t.label or t.series_id or f"Serie {i + 1}") for i, t in enumerate(clean_targets)]
        self.table.setColumnCount(len(headers))
        self.table.setHorizontalHeaderLabels(headers)
        self.table.setRowCount(row_count)

        for row in range(row_count):
            idx_item = QTableWidgetItem(str(row))
            idx_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 0, idx_item)

            x_value = None
            for target in clean_targets:
                if row < len(target.x_values):
                    x_value = target.x_values[row]
                    break
            x_item = QTableWidgetItem(compact(x_value, digits=9) if x_value is not None else "")
            x_item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.table.setItem(row, 1, x_item)

            for col, target in enumerate(clean_targets, start=2):
                y_value = target.y_values[row] if row < len(target.y_values) else None
                item = QTableWidgetItem(compact(y_value, digits=9) if y_value is not None else "")
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                try:
                    item.setForeground(QBrush(QColor(target.color or "#1f77b4")))
                except Exception:
                    pass
                self.table.setItem(row, col, item)


class StyleDialog(QDialog):
    def __init__(self, parent: QWidget, style: StyleModel) -> None:
        super().__init__(parent)
        self.setWindowTitle("Plot Style Editor")
        self.setModal(True)
        self._style = copy.deepcopy(style)

        root = QVBoxLayout(self)
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset"))
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(PRESETS)
        self.preset_combo.setCurrentText(self._style.preset_name)
        preset_row.addWidget(self.preset_combo, 1)
        self.apply_preset_button = QPushButton("Preset anwenden")
        preset_row.addWidget(self.apply_preset_button)
        root.addLayout(preset_row)

        form = QFormLayout()
        self.background_button = ColorButton(self._style.background_color)
        self.axes_face_button = ColorButton(self._style.axes_facecolor)
        self.text_button = ColorButton(self._style.text_color)
        self.grid_button = ColorButton(self._style.grid_color)
        self.legend_face_button = ColorButton(self._style.legend_facecolor)
        self.legend_edge_button = ColorButton(self._style.legend_edgecolor)
        self.font_edit = QLineEdit(self._style.font_family)
        self.font_size_spin = QSpinBox()
        self.font_size_spin.setRange(6, 32)
        self.font_size_spin.setValue(self._style.font_size)
        self.axis_label_size_spin = QSpinBox()
        self.axis_label_size_spin.setRange(6, 40)
        self.axis_label_size_spin.setValue(self._style.axis_label_size)
        self.tick_label_size_spin = QSpinBox()
        self.tick_label_size_spin.setRange(6, 40)
        self.tick_label_size_spin.setValue(self._style.tick_label_size)
        self.title_size_spin = QSpinBox()
        self.title_size_spin.setRange(6, 40)
        self.title_size_spin.setValue(self._style.title_size)
        self.figure_title_size_spin = QSpinBox()
        self.figure_title_size_spin.setRange(6, 48)
        self.figure_title_size_spin.setValue(self._style.figure_title_size)
        self.line_width_spin = CompactDoubleSpinBox()
        self.line_width_spin.setRange(0.1, 20.0)
        self.line_width_spin.setValue(self._style.default_line_width)
        self.marker_size_spin = CompactDoubleSpinBox()
        self.marker_size_spin.setRange(0.0, 30.0)
        self.marker_size_spin.setValue(self._style.default_marker_size)
        self.grid_visible = QCheckBox()
        self.grid_visible.setChecked(self._style.grid_visible)
        self.grid_alpha_spin = CompactDoubleSpinBox()
        self.grid_alpha_spin.setRange(0.0, 1.0)
        self.grid_alpha_spin.setSingleStep(0.05)
        self.grid_alpha_spin.setValue(self._style.grid_alpha)
        self.subplot_title_visible_check = QCheckBox()
        self.subplot_title_visible_check.setChecked(self._style.subplot_title_visible)
        self.figure_title_visible_check = QCheckBox()
        self.figure_title_visible_check.setChecked(self._style.figure_title_visible)
        self.legend_visible = QCheckBox()
        self.legend_visible.setChecked(self._style.legend_visible)
        self.legend_pos_combo = QComboBox()
        self.legend_pos_combo.addItems(LEGEND_POSITIONS)
        self.legend_pos_combo.setCurrentText(self._style.legend_position)
        for label, widget in [
            ("Background", self.background_button),
            ("Axes background", self.axes_face_button),
            ("Text", self.text_button),
            ("Grid", self.grid_button),
            ("Legend background", self.legend_face_button),
            ("Legend border", self.legend_edge_button),
            ("Font family", self.font_edit),
            ("Base font size", self.font_size_spin),
            ("Tick label size", self.tick_label_size_spin),
            ("Axis label size", self.axis_label_size_spin),
            ("Title size", self.title_size_spin),
            ("Figure title size", self.figure_title_size_spin),
            ("Default line width", self.line_width_spin),
            ("Default marker size", self.marker_size_spin),
            ("Show subplot titles", self.subplot_title_visible_check),
            ("Show figure title", self.figure_title_visible_check),
            ("Grid visible", self.grid_visible),
            ("Grid alpha", self.grid_alpha_spin),
            ("Legend visible", self.legend_visible),
            ("Legend position", self.legend_pos_combo),
        ]:
            form.addRow(label, widget)
        root.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        root.addWidget(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        self.apply_preset_button.clicked.connect(self._apply_preset)
        self.resize(440, 520)

    def _apply_preset(self) -> None:
        style = StyleModel.preset(self.preset_combo.currentText())
        self.background_button.setColor(style.background_color)
        self.axes_face_button.setColor(style.axes_facecolor)
        self.text_button.setColor(style.text_color)
        self.grid_button.setColor(style.grid_color)
        self.legend_face_button.setColor(style.legend_facecolor)
        self.legend_edge_button.setColor(style.legend_edgecolor)
        self.font_edit.setText(style.font_family)
        self.font_size_spin.setValue(style.font_size)
        self.tick_label_size_spin.setValue(style.tick_label_size)
        self.axis_label_size_spin.setValue(style.axis_label_size)
        self.title_size_spin.setValue(style.title_size)
        self.figure_title_size_spin.setValue(style.figure_title_size)
        self.line_width_spin.setValue(style.default_line_width)
        self.marker_size_spin.setValue(style.default_marker_size)
        self.subplot_title_visible_check.setChecked(style.subplot_title_visible)
        self.figure_title_visible_check.setChecked(style.figure_title_visible)
        self.grid_visible.setChecked(style.grid_visible)
        self.grid_alpha_spin.setValue(style.grid_alpha)
        self.legend_visible.setChecked(style.legend_visible)
        self.legend_pos_combo.setCurrentText(style.legend_position)

    def result_style(self) -> StyleModel:
        return StyleModel(
            preset_name=self.preset_combo.currentText(),
            background_color=self.background_button.color(),
            axes_facecolor=self.axes_face_button.color(),
            text_color=self.text_button.color(),
            grid_color=self.grid_button.color(),
            legend_facecolor=self.legend_face_button.color(),
            legend_edgecolor=self.legend_edge_button.color(),
            default_line_width=self.line_width_spin.value(),
            default_marker_size=self.marker_size_spin.value(),
            font_family=self.font_edit.text().strip() or "DejaVu Sans",
            font_size=self.font_size_spin.value(),
            axis_label_size=self.axis_label_size_spin.value(),
            tick_label_size=self.tick_label_size_spin.value(),
            title_size=self.title_size_spin.value(),
            figure_title_size=self.figure_title_size_spin.value(),
            subplot_title_visible=self.subplot_title_visible_check.isChecked(),
            figure_title_visible=self.figure_title_visible_check.isChecked(),
            grid_visible=self.grid_visible.isChecked(),
            grid_alpha=self.grid_alpha_spin.value(),
            legend_visible=self.legend_visible.isChecked(),
            legend_position=self.legend_pos_combo.currentText(),
            tight_layout=True,
        )


class PlotStyleEditor(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.settings = QSettings(APP_ORG, APP_NAME)
        self.setWindowTitle(APP_NAME)
        self.resize(1680, 980)

        self.setDockOptions(QMainWindow.AllowNestedDocks | QMainWindow.AllowTabbedDocks)
    
        self.loading_ui = False
        self.current_project_path: Path | None = None
        self.project = ProjectModel(style=StyleModel.preset("Light Engineering"))
        self.catalog = SignalCatalog()
        self.preview_csv = CsvPreviewData()
        self.config_data: dict[str, Any] = {}
        self.axis_style_clipboard: dict[str, Any] | None = None
        self.diagnosis: dict[str, Any] = {}
        self._figure_drop_target_index: int | None = None

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self._build_statusbar()
        self._build_docks()
        self._populate_style_menu()
        self._apply_saved_style()
        self._restore_window_state()
        self._restore_plot_style_state()
        self._auto_open_defaults()
        self._ensure_minimum_project()
        self.showMaximized()
        self.refresh_all()

    # ---------- UI build ----------
    def _build_actions(self) -> None:
        self.action_new = QAction("Neu", self)
        self.action_open = QAction("Öffnen…", self)
        self.action_save = QAction("Speichern", self)
        self.action_save_as = QAction("Speichern unter…", self)
        self.action_load_config = QAction("Config laden…", self)
        self.action_load_signals = QAction("Signals laden…", self)
        self.action_load_csv = QAction("Preview CSV laden…", self)
        self.action_show_available_only = QAction("Nur CSV-Signale", self)
        self.action_show_available_only.setCheckable(True)
        self.action_show_available_only.setToolTip("Zeigt nur Signale an, die in der geladenen Preview-CSV vorhanden sind")
        self.action_show_available_only.toggled.connect(self.populate_signal_tree)
        self.action_exit = QAction("Beenden", self)
        self.action_style_editor = QAction("PlotStyle Editor…", self)
        self.action_add_figure = QAction("Figure hinzufügen", self)
        self.action_copy_figure = QAction("Figure kopieren", self)
        self.action_delete_figure = QAction("Figure löschen", self)
        self.action_add_subplot = QAction("Subplot hinzufügen", self)
        self.action_copy_subplot = QAction("Subplot kopieren", self)
        self.action_delete_subplot = QAction("Subplot löschen", self)
        self.action_move_subplot_up = QAction("Subplot hoch", self)
        self.action_move_subplot_down = QAction("Subplot runter", self)
        self.action_add_axis = QAction("Y-Achse hinzufügen", self)
        self.action_delete_axis = QAction("Y-Achse löschen", self)
        self.action_add_series = QAction("Serie hinzufügen", self)
        self.action_delete_series = QAction("Serie löschen", self)
        self.action_move_series_up = QAction("Serie hoch", self)
        self.action_move_series_down = QAction("Serie runter", self)
        self.action_auto_timing_cart = QAction("Auto Timing Cartesian", self)
        self.action_auto_timing_polar = QAction("Auto Timing Polar", self)
        self.action_regenerate_events = QAction("Events aus Config neu erzeugen", self)
        self.action_save_subplot_template = QAction("Subplot-Template speichern…", self)
        self.action_load_subplot_template = QAction("Subplot-Template laden…", self)
        self.action_save_figure_template = QAction("Figure-Template speichern…", self)
        self.action_load_figure_template = QAction("Figure-Template laden…", self)
        self.action_save_layout_template = QAction("Layout-Template speichern…", self)
        self.action_load_layout_template = QAction("Layout-Template laden…", self)
        self.action_save_style_template = QAction("Plot-Style speichern…", self)
        self.action_load_style_template = QAction("Plot-Style laden…", self)

        self.action_new.triggered.connect(self.new_project)
        self.action_open.triggered.connect(self.open_project)
        self.action_save.triggered.connect(self.save_project)
        self.action_save_as.triggered.connect(self.save_project_as)
        self.action_load_config.triggered.connect(self.load_config_json)
        self.action_load_signals.triggered.connect(self.load_signals_json)
        self.action_load_csv.triggered.connect(self.load_preview_csv)
        self.action_exit.triggered.connect(self.close)
        self.action_style_editor.triggered.connect(self.open_style_editor)
        self.action_add_figure.triggered.connect(self.add_figure)
        self.action_copy_figure.triggered.connect(self.copy_figure)
        self.action_delete_figure.triggered.connect(self.delete_figure)
        self.action_add_subplot.triggered.connect(self.add_subplot)
        self.action_copy_subplot.triggered.connect(self.copy_subplot)
        self.action_delete_subplot.triggered.connect(self.delete_subplot)
        self.action_move_subplot_up.triggered.connect(lambda: self.move_subplot(-1))
        self.action_move_subplot_down.triggered.connect(lambda: self.move_subplot(1))
        self.action_add_axis.triggered.connect(self.add_axis)
        self.action_delete_axis.triggered.connect(self.delete_axis)
        self.action_add_series.triggered.connect(self.add_series)
        self.action_delete_series.triggered.connect(self.delete_series)
        self.action_move_series_up.triggered.connect(lambda: self.move_series(-1))
        self.action_move_series_down.triggered.connect(lambda: self.move_series(1))
        self.action_auto_timing_cart.triggered.connect(lambda: self.create_auto_timing_plot("timing_cartesian"))
        self.action_auto_timing_polar.triggered.connect(lambda: self.create_auto_timing_plot("timing_polar"))
        self.action_regenerate_events.triggered.connect(self.regenerate_events_from_config_for_all_subplots)
        self.action_save_subplot_template.triggered.connect(self.save_subplot_template)
        self.action_load_subplot_template.triggered.connect(self.load_subplot_template)
        self.action_save_figure_template.triggered.connect(self.save_figure_template)
        self.action_load_figure_template.triggered.connect(self.load_figure_template)
        self.action_save_layout_template.triggered.connect(self.save_layout_template)
        self.action_load_layout_template.triggered.connect(self.load_layout_template)
        self.action_save_style_template.triggered.connect(self.save_style_template)
        self.action_load_style_template.triggered.connect(self.load_style_template)

    def _build_menus(self) -> None:
        self.file_menu = self.menuBar().addMenu("Datei")
        for action in [
            self.action_new,
            self.action_open,
            self.action_save,
            self.action_save_as,
            self.action_load_config,
            self.action_load_signals,
            self.action_load_csv,
        ]:
            self.file_menu.addAction(action)
        self.file_menu.addSeparator()
        self.file_menu.addAction(self.action_exit)

        self.project_menu = self.menuBar().addMenu("Projekt")
        for action in [
            self.action_add_figure,
            self.action_copy_figure,
            self.action_delete_figure,
            self.action_add_subplot,
            self.action_copy_subplot,
            self.action_delete_subplot,
            self.action_move_subplot_up,
            self.action_move_subplot_down,
            self.action_add_axis,
            self.action_delete_axis,
            self.action_add_series,
            self.action_delete_series,
            self.action_move_series_up,
            self.action_move_series_down,
        ]:
            self.project_menu.addAction(action)

        self.templates_menu = self.menuBar().addMenu("Templates")
        for action in [
            self.action_save_subplot_template,
            self.action_load_subplot_template,
            self.action_save_figure_template,
            self.action_load_figure_template,
            self.action_save_layout_template,
            self.action_load_layout_template,
            self.action_save_style_template,
            self.action_load_style_template,
        ]:
            self.templates_menu.addAction(action)

        self.auto_menu = self.menuBar().addMenu("Automatik")
        self.auto_menu.addAction(self.action_auto_timing_cart)
        self.auto_menu.addAction(self.action_auto_timing_polar)
        self.auto_menu.addSeparator()
        self.auto_menu.addAction(self.action_regenerate_events)

        self.view_menu = self.menuBar().addMenu("Ansicht")
        self.style_menu = self.menuBar().addMenu("Style")
        self.style_menu.addAction(self.action_style_editor)
        self.style_menu.addSeparator()
        self.style_action_group = QActionGroup(self)

    def _build_toolbar(self) -> None:
        bar = QToolBar("Main", self)
        bar.setObjectName("main_toolbar")
        bar.setMovable(False)
        bar.setFloatable(False)
        bar.setToolButtonStyle(Qt.ToolButtonIconOnly)
        bar.setIconSize(bar.iconSize().expandedTo(bar.iconSize()))
        self.addToolBar(Qt.TopToolBarArea, bar)

        style = self.style()
        self.action_new.setIcon(style.standardIcon(QStyle.SP_FileIcon))
        self.action_open.setIcon(style.standardIcon(QStyle.SP_DialogOpenButton))
        self.action_save.setIcon(style.standardIcon(QStyle.SP_DialogSaveButton))
        self.action_load_config.setIcon(style.standardIcon(QStyle.SP_FileDialogDetailedView))
        self.action_load_signals.setIcon(style.standardIcon(QStyle.SP_FileDialogListView))
        self.action_load_csv.setIcon(style.standardIcon(QStyle.SP_DriveHDIcon))
        self.action_add_figure.setIcon(style.standardIcon(QStyle.SP_FileDialogNewFolder))
        self.action_add_subplot.setIcon(style.standardIcon(QStyle.SP_FileDialogContentsView))
        self.action_add_axis.setIcon(style.standardIcon(QStyle.SP_ArrowRight))
        self.action_add_series.setIcon(style.standardIcon(QStyle.SP_ArrowDown))
        self.action_auto_timing_cart.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.action_auto_timing_polar.setIcon(style.standardIcon(QStyle.SP_BrowserReload))
        self.action_show_available_only.setIcon(style.standardIcon(QStyle.SP_DialogYesButton))
        self.action_regenerate_events.setIcon(style.standardIcon(QStyle.SP_BrowserReload))

        for action in [
            self.action_new,
            self.action_open,
            self.action_save,
            self.action_load_config,
            self.action_load_signals,
            self.action_load_csv,
        ]:
            bar.addAction(action)
        bar.addSeparator()
        for action in [
            self.action_add_figure,
            self.action_add_subplot,
            self.action_add_axis,
            self.action_add_series,
        ]:
            bar.addAction(action)
        bar.addSeparator()
        bar.addAction(self.action_auto_timing_cart)
        bar.addAction(self.action_auto_timing_polar)
        bar.addAction(self.action_regenerate_events)
        bar.addSeparator()
        bar.addAction(self.action_show_available_only)

        style_button = QToolButton()
        style_button.setAutoRaise(True)
        style_button.setIcon(style.standardIcon(QStyle.SP_FileDialogInfoView))
        style_button.setToolTip("Plot-Stil bearbeiten")
        style_button.clicked.connect(self.open_style_editor)
        bar.addWidget(style_button)

    def _build_statusbar(self) -> None:
        status = QStatusBar(self)
        self.setStatusBar(status)
        self.status_project = QLabel()
        self.status_config = QLabel()
        self.status_signals = QLabel()
        self.status_csv = QLabel()
        self.status_detect = QLabel()
        for label in [self.status_project, self.status_config, self.status_signals, self.status_csv, self.status_detect]:
            label.setFrameStyle(QFrame.Panel | QFrame.Sunken)
            label.setContentsMargins(6, 0, 6, 0)
            status.addPermanentWidget(label)

    def _build_docks(self) -> None:
        self.project_panel = self._build_project_panel()
        self.signals_panel = self._build_signals_panel()
        self.inspector_tabs = self._build_inspector_tabs()
        self.preview_widget = MatplotlibPreview()
        self.preview_widget.seriesDoubleClicked.connect(self.focus_series_from_preview)
        self.preview_widget.seriesMoveRequested.connect(self.move_series_between_subplots)
        self.json_preview = QPlainTextEdit()
        self.json_preview.setReadOnly(True)
        self.json_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.json_preview.setMinimumHeight(220)

        self.project_dock = self._create_dock("Project", self._make_scroll(self.project_panel))
        self.signals_dock = self._create_dock("Signals", self._make_scroll(self.signals_panel))
        self.inspector_dock = self._create_dock("Inspector", self._make_scroll(self.inspector_tabs))
        self.preview_dock = self._create_dock("Live Preview", self.preview_widget)
        self.json_dock = self._create_dock("YAML Preview", self.json_preview)

        self.addDockWidget(Qt.LeftDockWidgetArea, self.project_dock)
        self.splitDockWidget(self.project_dock, self.signals_dock, Qt.Vertical)
        self.addDockWidget(Qt.RightDockWidgetArea, self.preview_dock)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.inspector_dock)
        self.splitDockWidget(self.inspector_dock, self.json_dock, Qt.Horizontal)
        self.resizeDocks([self.project_dock, self.signals_dock], [400, 550], Qt.Vertical)
        self.resizeDocks([self.inspector_dock, self.json_dock], [940, 620], Qt.Horizontal)

        self.all_docks = [self.project_dock, self.signals_dock, self.preview_dock, self.inspector_dock, self.json_dock]
        for dock in self.all_docks:
            self.view_menu.addAction(dock.toggleViewAction())

    def _create_dock(self, title: str, widget: QWidget) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(f"dock_{title.lower().replace(' ', '_')}")
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        dock.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return dock

    def _make_scroll(self, widget: QWidget) -> QWidget:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        area.setWidget(widget)
        return area

    def _build_project_panel(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        top = QGroupBox("Project")
        form = QFormLayout(top)
        self.project_name_edit = QLineEdit()
        self.project_name_edit.editingFinished.connect(self.on_project_meta_changed)
        self.figure_title_edit = QLineEdit()
        self.figure_title_edit.editingFinished.connect(self.on_figure_meta_changed)
        self.figure_rows_spin = QSpinBox()
        self.figure_rows_spin.setRange(1, 12)
        self.figure_rows_spin.valueChanged.connect(self.on_figure_layout_changed)
        self.figure_cols_spin = QSpinBox()
        self.figure_cols_spin.setRange(1, 12)
        self.figure_cols_spin.valueChanged.connect(self.on_figure_layout_changed)
        self.cylinder_combo = QComboBox()
        self.cylinder_combo.setEditable(True)
        self.cylinder_combo.currentTextChanged.connect(self.on_cylinder_changed)
        form.addRow("Project name", self.project_name_edit)
        form.addRow("Figure title", self.figure_title_edit)
        form.addRow("Rows", self.figure_rows_spin)
        form.addRow("Cols", self.figure_cols_spin)
        form.addRow("Cylinder", self.cylinder_combo)
        layout.addWidget(top)

        grid = QGridLayout()
        self.figure_list = FigureListWidget()
        self.figure_list.currentRowChanged.connect(self.on_figure_selection_changed)
        self.figure_list.subplotDropped.connect(self.on_subplot_dropped_on_figure)
        self.figure_list.dragFeedback.connect(self.on_project_drag_feedback)
        self.figure_list.targetFigureChanged.connect(self.on_project_drag_target_changed)
        self.subplot_list = SubplotListWidget()
        self.subplot_list.currentRowChanged.connect(self.on_subplot_selection_changed)
        self.subplot_list.dragFeedback.connect(self.on_project_drag_feedback)
        grid.addWidget(QLabel("Figures"), 0, 0)
        grid.addWidget(QLabel("Subplots"), 0, 1)
        grid.addWidget(self.figure_list, 1, 0)
        grid.addWidget(self.subplot_list, 1, 1)
        self.figure_selection_info = QLabel("Aktive Figure: –")
        self.figure_selection_info.setWordWrap(True)
        self.subplot_selection_info = QLabel("Aktiver Subplot: –")
        self.subplot_selection_info.setWordWrap(True)
        grid.addWidget(self.figure_selection_info, 2, 0)
        grid.addWidget(self.subplot_selection_info, 2, 1)
        layout.addLayout(grid, 1)

        button_grid = QGridLayout()
        buttons = [
            ("+ Figure", self.add_figure),
            ("Copy Figure", self.copy_figure),
            ("Delete Figure", self.delete_figure),
            ("+ Subplot", self.add_subplot),
            ("Copy Subplot", self.copy_subplot),
            ("Delete Subplot", self.delete_subplot),
            ("Subplot ↑", lambda: self.move_subplot(-1)),
            ("Subplot ↓", lambda: self.move_subplot(1)),
        ]
        for idx, (text, callback) in enumerate(buttons):
            button = QPushButton(text)
            button.clicked.connect(callback)
            button_grid.addWidget(button, idx // 2, idx % 2)
        layout.addLayout(button_grid)
        return root

    def _build_signals_panel(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        info_box = QGroupBox("Signal source")
        form = QFormLayout(info_box)
        self.signals_path_label = QLineEdit()
        self.signals_path_label.setReadOnly(True)
        self.csv_path_label = QLineEdit()
        self.csv_path_label.setReadOnly(True)
        self.signals_filter_edit = QLineEdit()
        self.signals_filter_edit.setPlaceholderText("Filter")
        self.signals_filter_edit.textChanged.connect(self.populate_signal_tree)
        self.available_only_check = QCheckBox("Nur in Preview-CSV vorhandene Signale")
        self.available_only_check.toggled.connect(self.action_show_available_only.setChecked)
        self.action_show_available_only.toggled.connect(self.available_only_check.setChecked)
        form.addRow("Signals JSON", self.signals_path_label)
        form.addRow("Preview CSV", self.csv_path_label)
        form.addRow("Filter", self.signals_filter_edit)
        form.addRow("Anzeige", self.available_only_check)
        layout.addWidget(info_box)

        self.signal_tree = SignalTreeWidget()
        self.signal_tree.itemDoubleClicked.connect(self.on_signal_tree_double_clicked)
        layout.addWidget(self.signal_tree, 1)

        hint = QLabel("Signale per Drag & Drop auf die Serienliste ziehen oder doppelklicken.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return root

    def _build_inspector_tabs(self) -> QWidget:
        tabs = QTabWidget()
        tabs.setDocumentMode(True)
        tabs.addTab(self._make_scroll(self._build_subplot_tab()), "Subplot")
        tabs.addTab(self._make_scroll(self._build_axes_tab()), "Axes")
        tabs.addTab(self._make_scroll(self._build_series_tab()), "Series")
        tabs.addTab(self._make_scroll(self._build_events_tab()), "Events")
        tabs.addTab(self._make_scroll(self._build_diagnosis_tab()), "Diagnosis")
        tabs.addTab(self._make_scroll(self._build_notes_tab()), "Notes")
        return tabs

    def _build_subplot_tab(self) -> QWidget:
        root = QWidget()
        form = QFormLayout(root)
        self.subplot_title_edit = QLineEdit()
        self.subplot_title_edit.editingFinished.connect(self.on_subplot_meta_changed)
        self.subplot_show_title_check = QCheckBox()
        self.subplot_show_title_check.setChecked(True)
        self.subplot_show_title_check.stateChanged.connect(self.on_subplot_meta_changed)
        self.subplot_type_combo = QComboBox()
        self.subplot_type_combo.addItems(PLOT_TYPES)
        self.subplot_type_combo.currentTextChanged.connect(self.on_subplot_meta_changed)
        self.subplot_x_signal_edit = QLineEdit()
        self.subplot_x_signal_edit.editingFinished.connect(self.on_subplot_meta_changed)
        self.subplot_x_title_edit = QLineEdit()
        self.subplot_x_title_edit.editingFinished.connect(self.on_subplot_meta_changed)
        self.subplot_x_unit_combo = QComboBox()
        self.subplot_x_unit_combo.addItems(X_UNIT_PRESETS)
        self.subplot_x_unit_combo.currentTextChanged.connect(self.on_subplot_meta_changed)
        self.subplot_x_scale_spin = CompactDoubleSpinBox()
        self.subplot_x_scale_spin.setRange(-1e12, 1e12)
        self.subplot_x_scale_spin.setValue(1.0)
        self.subplot_x_scale_spin.valueChanged.connect(self.on_subplot_meta_changed)
        self.subplot_x_offset_spin = CompactDoubleSpinBox()
        self.subplot_x_offset_spin.setRange(-1e12, 1e12)
        self.subplot_x_offset_spin.valueChanged.connect(self.on_subplot_meta_changed)
        self.subplot_x_limit_mode_combo = QComboBox()
        self.subplot_x_limit_mode_combo.addItems(X_LIMIT_MODES)
        self.subplot_x_limit_mode_combo.currentTextChanged.connect(self.on_subplot_meta_changed)
        self.subplot_x_min_spin = CompactDoubleSpinBox()
        self.subplot_x_min_spin.setRange(-1e12, 1e12)
        self.subplot_x_min_spin.valueChanged.connect(self.on_subplot_meta_changed)
        self.subplot_x_max_spin = CompactDoubleSpinBox()
        self.subplot_x_max_spin.setRange(-1e12, 1e12)
        self.subplot_x_max_spin.valueChanged.connect(self.on_subplot_meta_changed)
        self.subplot_x_start_zero_check = QCheckBox()
        self.subplot_x_start_zero_check.setChecked(True)
        self.subplot_x_start_zero_check.setToolTip("Startet die X-Achse im Auto-Modus bei 0")
        self.subplot_x_start_zero_check.stateChanged.connect(self.on_subplot_meta_changed)
        self.subplot_grid_check = QCheckBox()
        self.subplot_grid_check.stateChanged.connect(self.on_subplot_meta_changed)
        self.subplot_legend_check = QCheckBox()
        self.subplot_legend_check.stateChanged.connect(self.on_subplot_meta_changed)
        self.subplot_legend_pos_combo = QComboBox()
        self.subplot_legend_pos_combo.addItems(LEGEND_POSITIONS)
        self.subplot_legend_pos_combo.currentTextChanged.connect(self.on_subplot_meta_changed)
        form.addRow("Title", self.subplot_title_edit)
        form.addRow("Show title", self.subplot_show_title_check)
        form.addRow("Plot type", self.subplot_type_combo)
        form.addRow("X signal", self.subplot_x_signal_edit)
        form.addRow("X title", self.subplot_x_title_edit)
        form.addRow("X unit", self.subplot_x_unit_combo)
        form.addRow("X scale factor", self.subplot_x_scale_spin)
        form.addRow("X offset", self.subplot_x_offset_spin)
        form.addRow("X limits", self.subplot_x_limit_mode_combo)
        form.addRow("X min", self.subplot_x_min_spin)
        form.addRow("X max", self.subplot_x_max_spin)
        form.addRow("X start at 0", self.subplot_x_start_zero_check)
        form.addRow("Show grid", self.subplot_grid_check)
        form.addRow("Show legend", self.subplot_legend_check)
        form.addRow("Legend position", self.subplot_legend_pos_combo)
        auto_box = QHBoxLayout()
        bt1 = QPushButton("Auto Timing Cartesian")
        bt2 = QPushButton("Auto Timing Polar")
        bt1.clicked.connect(lambda: self.create_auto_timing_plot("timing_cartesian"))
        bt2.clicked.connect(lambda: self.create_auto_timing_plot("timing_polar"))
        auto_box.addWidget(bt1)
        auto_box.addWidget(bt2)
        form.addRow("Auto plots", auto_box)
        x_range_box = QHBoxLayout()
        x_auto_btn = QPushButton("X Auto")
        x_360_btn = QPushButton("0…360")
        x_720_btn = QPushButton("0…720")
        x_pm180_btn = QPushButton("-180…180")
        x_pm360_btn = QPushButton("-360…360")
        x_auto_btn.clicked.connect(lambda: self.apply_x_range_preset("auto"))
        x_360_btn.clicked.connect(lambda: self.apply_x_range_preset("0_360"))
        x_720_btn.clicked.connect(lambda: self.apply_x_range_preset("0_720"))
        x_pm180_btn.clicked.connect(lambda: self.apply_x_range_preset("pm180"))
        x_pm360_btn.clicked.connect(lambda: self.apply_x_range_preset("pm360"))
        for btn in [x_auto_btn, x_360_btn, x_720_btn, x_pm180_btn, x_pm360_btn]:
            btn.setAutoDefault(False)
            x_range_box.addWidget(btn)
        form.addRow("X presets", x_range_box)
        return root

    def _build_axes_tab(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        self.axis_list = QListWidget()
        self.axis_list.setAlternatingRowColors(True)
        self.axis_list.currentRowChanged.connect(self.on_axis_selection_changed)
        layout.addWidget(self.axis_list)
        buttons = QHBoxLayout()
        add_btn = QPushButton("+ Axis")
        del_btn = QPushButton("Delete")
        add_btn.clicked.connect(self.add_axis)
        del_btn.clicked.connect(self.delete_axis)
        buttons.addWidget(add_btn)
        buttons.addWidget(del_btn)
        layout.addLayout(buttons)
        form = QFormLayout()
        self.axis_title_edit = QLineEdit()
        self.axis_title_edit.editingFinished.connect(self.on_axis_meta_changed)
        self.axis_side_combo = QComboBox()
        self.axis_side_combo.addItems(AXIS_SIDES)
        self.axis_side_combo.currentTextChanged.connect(self.on_axis_meta_changed)
        self.axis_offset_spin = CompactDoubleSpinBox()
        self.axis_offset_spin.setRange(-2.0, 4.0)
        self.axis_offset_spin.setSingleStep(0.05)
        self.axis_offset_spin.valueChanged.connect(self.on_axis_meta_changed)
        self.axis_color_button = ColorButton("#1f77b4")
        self.axis_color_button.colorChanged.connect(self.on_axis_meta_changed)
        self.axis_visible_check = QCheckBox()
        self.axis_visible_check.stateChanged.connect(self.on_axis_meta_changed)
        self.axis_limit_mode_combo = QComboBox()
        self.axis_limit_mode_combo.addItems(["data", "manual"])
        self.axis_limit_mode_combo.currentTextChanged.connect(self.on_axis_meta_changed)
        self.axis_y_min_spin = CompactDoubleSpinBox()
        self.axis_y_min_spin.setRange(-1e12, 1e12)
        self.axis_y_min_spin.valueChanged.connect(self.on_axis_meta_changed)
        self.axis_y_max_spin = CompactDoubleSpinBox()
        self.axis_y_max_spin.setRange(-1e12, 1e12)
        self.axis_y_max_spin.valueChanged.connect(self.on_axis_meta_changed)
        self.axis_tick_step_spin = CompactDoubleSpinBox()
        self.axis_tick_step_spin.setRange(0.0, 1e12)
        self.axis_tick_step_spin.valueChanged.connect(self.on_axis_meta_changed)
        self.axis_minor_tick_step_spin = CompactDoubleSpinBox()
        self.axis_minor_tick_step_spin.setRange(0.0, 1e12)
        self.axis_minor_tick_step_spin.valueChanged.connect(self.on_axis_meta_changed)
        self.axis_major_grid_check = QCheckBox()
        self.axis_major_grid_check.stateChanged.connect(self.on_axis_meta_changed)
        self.axis_minor_grid_check = QCheckBox()
        self.axis_minor_grid_check.stateChanged.connect(self.on_axis_meta_changed)
        form.addRow("Axis title", self.axis_title_edit)
        form.addRow("Side", self.axis_side_combo)
        form.addRow("Spine offset", self.axis_offset_spin)
        form.addRow("Color", self.axis_color_button)
        form.addRow("Visible", self.axis_visible_check)
        form.addRow("Y limits", self.axis_limit_mode_combo)
        form.addRow("Y min", self.axis_y_min_spin)
        form.addRow("Y max", self.axis_y_max_spin)
        form.addRow("Y major step", self.axis_tick_step_spin)
        form.addRow("Y minor step", self.axis_minor_tick_step_spin)
        form.addRow("Y major grid", self.axis_major_grid_check)
        form.addRow("Y minor grid", self.axis_minor_grid_check)
        layout.addLayout(form)
        quick_row = QHBoxLayout()
        axis_auto_btn = QPushButton("Y Auto")
        axis_auto_btn.clicked.connect(self.reset_current_axis_to_auto)
        axis_nice_btn = QPushButton("Auto-Limits")
        axis_nice_btn.clicked.connect(self.fit_current_axis_to_data_nice)
        axis_swap_btn = QPushButton("Seite tauschen")
        axis_swap_btn.clicked.connect(self.swap_current_axis_side)
        axis_grid_btn = QPushButton("Grid Major+Minor")
        axis_grid_btn.clicked.connect(self.enable_current_axis_full_grid)
        for btn in [axis_auto_btn, axis_nice_btn, axis_swap_btn, axis_grid_btn]:
            btn.setAutoDefault(False)
            quick_row.addWidget(btn)
        layout.addLayout(quick_row)
        style_row = QHBoxLayout()
        axis_copy_style_btn = QPushButton("Stil kopieren")
        axis_copy_style_btn.clicked.connect(self.copy_current_axis_style)
        axis_paste_style_btn = QPushButton("Stil einfügen")
        axis_paste_style_btn.clicked.connect(self.paste_current_axis_style)
        axis_apply_subplot_btn = QPushButton("Auf Subplot")
        axis_apply_subplot_btn.clicked.connect(self.apply_current_axis_style_to_subplot)
        axis_apply_all_btn = QPushButton("Auf alle Subplots")
        axis_apply_all_btn.clicked.connect(self.apply_current_axis_style_to_all_subplots)
        for btn in [axis_copy_style_btn, axis_paste_style_btn, axis_apply_subplot_btn, axis_apply_all_btn]:
            btn.setAutoDefault(False)
            style_row.addWidget(btn)
        layout.addLayout(style_row)
        layout.addStretch(1)
        return root

    def _build_series_tab(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        self.series_list = SeriesListWidget()
        self.series_list.setAlternatingRowColors(True)
        self.series_list.currentRowChanged.connect(self.on_series_selection_changed)
        self.series_list.signalDropped.connect(self.add_series_from_signal)
        layout.addWidget(self.series_list)
        buttons = QGridLayout()
        for idx, (text, callback) in enumerate([
            ("+ Series", self.add_series),
            ("Delete", self.delete_series),
            ("↑", lambda: self.move_series(-1)),
            ("↓", lambda: self.move_series(1)),
        ]):
            btn = QPushButton(text)
            btn.clicked.connect(callback)
            buttons.addWidget(btn, idx // 4, idx % 4)
        layout.addLayout(buttons)

        form = QFormLayout()
        self.series_signal_edit = QLineEdit()
        self.series_signal_edit.editingFinished.connect(self.on_series_meta_changed)
        self.series_label_edit = QLineEdit()
        self.series_label_edit.editingFinished.connect(self.on_series_meta_changed)
        self.series_axis_combo = QComboBox()
        self.series_axis_combo.currentTextChanged.connect(self.on_series_meta_changed)
        self.series_type_combo = QComboBox()
        self.series_type_combo.addItems(SERIES_TYPES)
        self.series_type_combo.currentTextChanged.connect(self.on_series_meta_changed)
        self.series_visible_check = QCheckBox()
        self.series_visible_check.stateChanged.connect(self.on_series_meta_changed)
        self.series_color_button = ColorButton("#1f77b4")
        self.series_color_button.colorChanged.connect(self.on_series_meta_changed)
        self.series_line_style_combo = QComboBox()
        self.series_line_style_combo.addItems(LINE_STYLES)
        self.series_line_style_combo.currentTextChanged.connect(self.on_series_meta_changed)
        self.series_marker_combo = QComboBox()
        self.series_marker_combo.addItems(MARKERS)
        self.series_marker_combo.currentTextChanged.connect(self.on_series_meta_changed)
        self.series_line_width_spin = CompactDoubleSpinBox()
        self.series_line_width_spin.setRange(0.0, 12.0)
        self.series_line_width_spin.valueChanged.connect(self.on_series_meta_changed)
        self.series_marker_size_spin = CompactDoubleSpinBox()
        self.series_marker_size_spin.setRange(0.0, 20.0)
        self.series_marker_size_spin.valueChanged.connect(self.on_series_meta_changed)
        self.series_unit_combo = QComboBox()
        self.series_unit_combo.addItems(SERIES_UNIT_PRESETS)
        self.series_unit_combo.currentTextChanged.connect(self.on_series_meta_changed)
        self.series_scale_spin = CompactDoubleSpinBox()
        self.series_scale_spin.setRange(-1e12, 1e12)
        self.series_scale_spin.setValue(1.0)
        self.series_scale_spin.valueChanged.connect(self.on_series_meta_changed)
        self.series_offset_spin = CompactDoubleSpinBox()
        self.series_offset_spin.setRange(-1e12, 1e12)
        self.series_offset_spin.valueChanged.connect(self.on_series_meta_changed)
        for label, widget in [
            ("Signal", self.series_signal_edit),
            ("Label", self.series_label_edit),
            ("Axis", self.series_axis_combo),
            ("Type", self.series_type_combo),
            ("Visible", self.series_visible_check),
            ("Color", self.series_color_button),
            ("Line style", self.series_line_style_combo),
            ("Marker", self.series_marker_combo),
            ("Line width", self.series_line_width_spin),
            ("Marker size", self.series_marker_size_spin),
            ("Display unit", self.series_unit_combo),
            ("Scale factor", self.series_scale_spin),
            ("Offset", self.series_offset_spin),
        ]:
            form.addRow(label, widget)
        layout.addLayout(form)
        layout.addStretch(1)
        return root

    def _build_events_tab(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        self.event_list = QListWidget()
        self.event_list.setAlternatingRowColors(True)
        self.event_list.currentRowChanged.connect(self.on_event_selection_changed)
        layout.addWidget(self.event_list)
        buttons = QGridLayout()
        self.event_add_button = QPushButton("+ Event")
        self.event_add_button.clicked.connect(self.add_event)
        buttons.addWidget(self.event_add_button, 0, 0)
        self.event_delete_button = QPushButton("Delete")
        self.event_delete_button.clicked.connect(self.delete_event)
        buttons.addWidget(self.event_delete_button, 0, 1)
        self.event_up_button = QPushButton("↑")
        self.event_up_button.clicked.connect(lambda: self.move_event(-1))
        buttons.addWidget(self.event_up_button, 0, 2)
        self.event_down_button = QPushButton("↓")
        self.event_down_button.clicked.connect(lambda: self.move_event(1))
        buttons.addWidget(self.event_down_button, 0, 3)
        self.event_from_config_button = QPushButton("Aus Config")
        self.event_from_config_button.clicked.connect(self.regenerate_events_from_config_for_current_subplot)
        buttons.addWidget(self.event_from_config_button, 0, 4)
        self.event_delete_auto_button = QPushButton("Nur Auto löschen")
        self.event_delete_auto_button.clicked.connect(self.delete_auto_events_current_subplot)
        buttons.addWidget(self.event_delete_auto_button, 1, 0, 1, 2)
        self.event_lock_auto_button = QPushButton("Auto sperren")
        self.event_lock_auto_button.clicked.connect(self.toggle_lock_auto_events_current_subplot)
        buttons.addWidget(self.event_lock_auto_button, 1, 2)
        self.event_hide_auto_button = QPushButton("Auto ausblenden")
        self.event_hide_auto_button.clicked.connect(self.toggle_hide_auto_events_current_subplot)
        buttons.addWidget(self.event_hide_auto_button, 1, 3)
        self.event_manual_to_auto_button = QPushButton("MAN→AUTO")
        self.event_manual_to_auto_button.clicked.connect(self.convert_current_manual_event_to_auto)
        buttons.addWidget(self.event_manual_to_auto_button, 1, 4)
        self.event_auto_scope_combo = QComboBox()
        for key, label in EVENT_FILTER_OPTIONS:
            self.event_auto_scope_combo.addItem(label, key)
        self.event_auto_scope_combo.currentIndexChanged.connect(lambda _idx: self.refresh_events())
        buttons.addWidget(self.event_auto_scope_combo, 2, 0, 1, 2)
        self.event_delete_auto_scope_button = QPushButton("Auto-Typ löschen")
        self.event_delete_auto_scope_button.clicked.connect(self.delete_auto_events_by_selected_type_current_subplot)
        buttons.addWidget(self.event_delete_auto_scope_button, 2, 2)
        self.event_hide_auto_scope_button = QPushButton("Auto-Typ ausblenden")
        self.event_hide_auto_scope_button.clicked.connect(self.toggle_hide_auto_events_by_selected_type_current_subplot)
        buttons.addWidget(self.event_hide_auto_scope_button, 2, 3)
        self.event_lock_auto_scope_button = QPushButton("Auto-Typ sperren")
        self.event_lock_auto_scope_button.clicked.connect(self.toggle_lock_auto_events_by_selected_type_current_subplot)
        buttons.addWidget(self.event_lock_auto_scope_button, 2, 4)
        layout.addLayout(buttons)
        form = QFormLayout()
        self.event_label_edit = QLineEdit()
        self.event_label_edit.editingFinished.connect(self.on_event_meta_changed)
        self.event_source_label = QLabel("-")
        self.event_locked_label = QLabel("-")
        self.event_source_note_label = QLabel("")
        self.event_source_note_label.setWordWrap(True)
        self.event_type_combo = QComboBox()
        self.event_type_combo.addItems(EVENT_TYPE_OPTIONS)
        self.event_type_combo.currentTextChanged.connect(self.on_event_meta_changed)
        self.event_x_spin = CompactDoubleSpinBox()
        self.event_x_spin.setRange(-1e12, 1e12)
        self.event_x_spin.valueChanged.connect(self.on_event_meta_changed)
        self.event_visible_check = QCheckBox()
        self.event_visible_check.stateChanged.connect(self.on_event_meta_changed)
        self.event_show_label_check = QCheckBox()
        self.event_show_label_check.stateChanged.connect(self.on_event_meta_changed)
        self.event_color_button = ColorButton("#666666")
        self.event_color_button.colorChanged.connect(self.on_event_meta_changed)
        self.event_line_style_combo = QComboBox()
        self.event_line_style_combo.addItems(LINE_STYLES)
        self.event_line_style_combo.currentTextChanged.connect(self.on_event_meta_changed)
        self.event_line_width_spin = CompactDoubleSpinBox()
        self.event_line_width_spin.setRange(0.1, 12.0)
        self.event_line_width_spin.valueChanged.connect(self.on_event_meta_changed)
        self.event_alpha_spin = CompactDoubleSpinBox()
        self.event_alpha_spin.setRange(0.0, 1.0)
        self.event_alpha_spin.setSingleStep(0.05)
        self.event_alpha_spin.valueChanged.connect(self.on_event_meta_changed)
        self.event_label_rotation_spin = CompactDoubleSpinBox()
        self.event_label_rotation_spin.setRange(-360.0, 360.0)
        self.event_label_rotation_spin.valueChanged.connect(self.on_event_meta_changed)
        self.event_label_font_size_spin = CompactDoubleSpinBox()
        self.event_label_font_size_spin.setRange(4.0, 48.0)
        self.event_label_font_size_spin.valueChanged.connect(self.on_event_meta_changed)
        self.event_label_bg_color_button = ColorButton("#ffffff")
        self.event_label_bg_color_button.colorChanged.connect(self.on_event_meta_changed)
        self.event_label_bg_alpha_spin = CompactDoubleSpinBox()
        self.event_label_bg_alpha_spin.setRange(0.0, 1.0)
        self.event_label_bg_alpha_spin.setSingleStep(0.05)
        self.event_label_bg_alpha_spin.valueChanged.connect(self.on_event_meta_changed)
        self.event_label_border_color_button = ColorButton("#ffffff")
        self.event_label_border_color_button.colorChanged.connect(self.on_event_meta_changed)
        self.event_label_y_spin = CompactDoubleSpinBox()
        self.event_label_y_spin.setRange(-1.0, 2.0)
        self.event_label_y_spin.setSingleStep(0.02)
        self.event_label_y_spin.valueChanged.connect(self.on_event_meta_changed)
        self.event_label_ha_combo = QComboBox()
        self.event_label_ha_combo.addItems(["left", "center", "right"])
        self.event_label_ha_combo.currentTextChanged.connect(self.on_event_meta_changed)
        self.event_label_va_combo = QComboBox()
        self.event_label_va_combo.addItems(["top", "center", "bottom"])
        self.event_label_va_combo.currentTextChanged.connect(self.on_event_meta_changed)
        for label, widget in [
            ("Label", self.event_label_edit),
            ("Quelle", self.event_source_label),
            ("Sperre", self.event_locked_label),
            ("Hinweis", self.event_source_note_label),
            ("Typ", self.event_type_combo),
            ("X position", self.event_x_spin),
            ("Visible", self.event_visible_check),
            ("Show label", self.event_show_label_check),
            ("Color", self.event_color_button),
            ("Line style", self.event_line_style_combo),
            ("Line width", self.event_line_width_spin),
            ("Alpha", self.event_alpha_spin),
            ("Label rotation", self.event_label_rotation_spin),
            ("Label font size", self.event_label_font_size_spin),
            ("Label Y", self.event_label_y_spin),
            ("Label H align", self.event_label_ha_combo),
            ("Label V align", self.event_label_va_combo),
            ("Label BG", self.event_label_bg_color_button),
            ("Label BG alpha", self.event_label_bg_alpha_spin),
            ("Label border", self.event_label_border_color_button),
        ]:
            form.addRow(label, widget)
        layout.addLayout(form)
        layout.addStretch(1)
        return root

    def _build_diagnosis_tab(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        self.diagnosis_text = QPlainTextEdit()
        self.diagnosis_text.setReadOnly(True)
        self.diagnosis_text.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.diagnosis_text)
        return root

    def _build_notes_tab(self) -> QWidget:
        root = QWidget()
        layout = QVBoxLayout(root)
        self.notes_edit = QPlainTextEdit()
        self.notes_edit.textChanged.connect(self.on_notes_changed)
        layout.addWidget(self.notes_edit)
        return root

    # ---------- settings & startup ----------
    def _populate_style_menu(self) -> None:
        for style_name in sorted(QStyleFactory.keys()):
            action = QAction(style_name, self)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, name=style_name: self.apply_ui_style(name))
            self.style_action_group.addAction(action)
            self.style_menu.addAction(action)

    def _apply_saved_style(self) -> None:
        style_name = str(self.settings.value("ui/style_name", QApplication.style().objectName()))
        self.apply_ui_style(style_name, announce=False)

    def apply_ui_style(self, style_name: str, announce: bool = True) -> None:
        available = {name.lower(): name for name in QStyleFactory.keys()}
        name = available.get(style_name.lower(), style_name)
        if name in QStyleFactory.keys():
            QApplication.setStyle(QStyleFactory.create(name))
            self.settings.setValue("ui/style_name", name)
            for action in self.style_action_group.actions():
                action.blockSignals(True)
                action.setChecked(action.text() == name)
                action.blockSignals(False)
            if announce:
                self.statusBar().showMessage(f"Style gewechselt: {name}", 2000)

    def _restore_window_state(self) -> None:
        geom = self.settings.value("window/geometry")
        state = self.settings.value("window/state")
        if geom:
            self.restoreGeometry(geom)
        if state:
            self.restoreState(state)

    def _store_plot_style_state(self) -> None:
        try:
            self.settings.setValue("plot_style/current_json", json.dumps(asdict(self.project.style), ensure_ascii=False))
        except Exception:
            pass

    def _restore_plot_style_state(self) -> None:
        raw = str(self.settings.value("plot_style/current_json", "") or "")
        if not raw:
            return
        try:
            data = json.loads(raw)
            if isinstance(data, dict):
                self.project.style = style_model_from_data(data)
        except Exception:
            pass

    def _get_nested_value(self, data: dict[str, Any], *paths: tuple[str, ...]) -> Any:
        for path in paths:
            current: Any = data
            ok = True
            for key in path:
                if isinstance(current, dict) and key in current:
                    current = current[key]
                else:
                    ok = False
                    break
            if ok and current not in (None, ""):
                return current
        return None

    def _normalize_cycle_type(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        if raw in {"2", "2t", "two_stroke", "two-stroke", "zweittakt"}:
            return "2T"
        if raw in {"4", "4t", "four_stroke", "four-stroke", "viertakt"}:
            return "4T"
        if "2" in raw and "t" in raw:
            return "2T"
        if "4" in raw and "t" in raw:
            return "4T"
        return "unknown"

    def _normalize_gasexchange_mode(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        aliases = {
            "valve": "valves",
            "valves": "valves",
            "port": "ports",
            "ports": "ports",
            "slot": "slots",
            "slots": "slots",
            "mixed": "mixed",
            "hybrid": "mixed",
            "combined": "mixed",
        }
        return aliases.get(raw, raw or "unknown")

    def _normalize_signal_mode(self, value: Any) -> str:
        raw = str(value or "").strip().lower()
        aliases = {
            "min": "minimal",
            "minimal": "minimal",
            "reduced": "minimal",
            "full": "full",
            "all": "full",
            "full_only": "full_only",
            "full-only": "full_only",
            "postprocessed": "postprocessed_dataframe_columns",
            "postprocessed_dataframe_columns": "postprocessed_dataframe_columns",
            "aliases": "plotting_series_aliases",
            "plotting_series_aliases": "plotting_series_aliases",
            "defaults": "default_plot_style_keys",
            "default_plot_style_keys": "default_plot_style_keys",
            "state": "state",
        }
        if raw in aliases:
            return aliases[raw]
        if raw in self.catalog.raw:
            return raw
        if self.catalog.raw.get("minimal"):
            return "minimal"
        if self.catalog.raw.get("full"):
            return "full"
        return raw or "unknown"

    def _validate_signal_catalog_path(self, path: Path) -> None:
        if path.name not in ALLOWED_SIGNAL_FILE_BASENAMES:
            allowed = ", ".join(sorted(ALLOWED_SIGNAL_FILE_BASENAMES))
            raise ValueError(f"Nur die freigegebene Signaldatei ist zulässig: {allowed}")

    def _auto_open_defaults(self) -> None:
        script_dir = Path(__file__).resolve().parent
        env_project_dir = Path(os.getenv("MOTORSIM_PROJECT_DIR") or Path.cwd()).expanduser().resolve()
        code_root = find_code_root(env_project_dir)
        project_paths = build_paths(project_dir=env_project_dir)

        stored_project = str(self.settings.value("session/current_project_path", "") or "")
        stored_signals = str(self.settings.value("session/signals_path", "") or "")
        stored_config = str(self.settings.value("session/config_path", "") or "")
        stored_csv = str(self.settings.value("session/preview_csv_path", "") or "")

        if stored_project and Path(stored_project).exists():
            self.load_project_from_path(Path(stored_project), silent=True)

        signal_candidates: list[Path] = []
        if stored_signals:
            signal_candidates.append(Path(stored_signals))
        signal_candidates.extend([
            env_project_dir / DEFAULT_SIGNALS_JSON,
            script_dir / DEFAULT_SIGNALS_JSON,
            code_root / 'scripts' / DEFAULT_SIGNALS_JSON,
            Path.cwd() / DEFAULT_SIGNALS_JSON,
        ])
        signals_candidate = next((p for p in signal_candidates if p.exists()), None)
        if signals_candidate:
            self.load_signals_from_path(signals_candidate, silent=True)

        config_candidates: list[Path] = []
        if stored_config:
            config_candidates.append(Path(stored_config))
        config_candidates.extend([
            project_paths.project_config_file,
            default_config_file(code_root),
            env_project_dir / DEFAULT_CONFIG_JSON,
            script_dir / DEFAULT_CONFIG_JSON,
            Path.cwd() / DEFAULT_CONFIG_JSON,
        ])
        config_candidate = next((p for p in config_candidates if p.exists()), None)
        if config_candidate:
            self.load_config_from_path(config_candidate, silent=True)

        csv_candidates: list[Path] = []
        if stored_csv:
            csv_candidates.append(Path(stored_csv))
        csv_candidates.extend([
            project_paths.project_out_dir / 'out_gui.csv',
            project_paths.project_dir / 'out_gui.csv',
            env_project_dir / 'out' / 'out_gui.csv',
            env_project_dir / 'results' / 'out_gui.csv',
        ])
        csv_candidate = next((p for p in csv_candidates if p.exists()), None)
        if csv_candidate:
            self.load_preview_csv_from_path(csv_candidate, silent=True)

        session_json = str(self.settings.value("session/project_json", "") or "")
        if not self.project.figures and session_json:
            try:
                self.project = self.project_from_dict(json.loads(session_json))
            except Exception:
                self.project = ProjectModel(style=StyleModel.preset("Light Engineering"))

    def _ensure_minimum_project(self) -> None:
        if not self.project.figures:
            self.project.figures = [FigureModel()]
        for fig in self.project.figures:
            if not fig.subplots:
                fig.subplots = [SubplotModel()]
            for subplot in fig.subplots:
                if not subplot.y_axes:
                    subplot.y_axes = [AxisModel(title="Y", side="left", color="#1f77b4")]
                if not subplot.series:
                    axis_id = subplot.y_axes[0].id
                    subplot.series = [SeriesModel(signal_key="p_cyl_pa", label="p_cyl_pa", axis_id=axis_id, color="#1f77b4")]
                for ser in subplot.series:
                    if not ser.axis_id and subplot.y_axes:
                        ser.axis_id = subplot.y_axes[0].id
        if not self.project.style:
            self.project.style = StyleModel.preset("Light Engineering")

    # ---------- model serialization ----------
    def project_to_dict(self) -> dict[str, Any]:
        return asdict(self.project)

    def project_from_dict(self, data: dict[str, Any]) -> ProjectModel:
        style_data: dict[str, Any] = {}
        style_sheet = str(data.get("style_sheet", "") or data.get("stylesheet", "") or "").strip()
        if style_sheet:
            try:
                base_path = Path(str(data.get("config_path", "") or "")).resolve().parent if data.get("config_path") else Path.cwd()
                style_path = Path(style_sheet)
                if not style_path.is_absolute():
                    style_path = base_path / style_path
                loaded_style = yaml.safe_load(style_path.read_text(encoding="utf-8")) or {}
                if isinstance(loaded_style, dict) and isinstance(loaded_style.get("style"), dict):
                    style_data.update(loaded_style["style"])
                elif isinstance(loaded_style, dict):
                    style_data.update(loaded_style)
            except Exception:
                pass
        if isinstance(data.get("style"), dict):
            style_data.update(data["style"])
        style = style_model_from_data(style_data or StyleModel.preset("Light Engineering").__dict__)
        figures: list[FigureModel] = []
        for fig_data in data.get("figures", []):
            subplots: list[SubplotModel] = []
            for sp_data in fig_data.get("subplots", []):
                y_axes = [axis_model_from_data(axis) for axis in sp_data.get("y_axes", [])] or [AxisModel(title="Y")]
                series = [series_model_from_data(series) for series in sp_data.get("series", [])]
                events = [event_model_from_data(event) for event in sp_data.get("events", [])]
                y_lines = [horizontal_line_model_from_data(y_line) for y_line in sp_data.get("y_lines", [])]
                subplots.append(SubplotModel(
                    id=sp_data.get("id", new_id()),
                    title=sp_data.get("title", "Subplot"),
                    show_title=bool(sp_data.get("show_title", True)),
                    plot_type=sp_data.get("plot_type", "line"),
                    x_signal=sp_data.get("x_signal", "theta_deg"),
                    x_title=sp_data.get("x_title", "Theta"),
                    x_unit_preset=sp_data.get("x_unit_preset", "deg"),
                    x_scale_factor=float(sp_data.get("x_scale_factor", 1.0) or 1.0),
                    x_offset=float(sp_data.get("x_offset", 0.0) or 0.0),
                    x_limit_mode=sp_data.get("x_limit_mode", "data"),
                    x_min=float(sp_data.get("x_min", 0.0) or 0.0),
                    x_max=float(sp_data.get("x_max", 720.0) or 720.0),
                    x_start_at_zero=bool(sp_data.get("x_start_at_zero", True)),
                    y_axes=y_axes,
                    series=series,
                    events=events,
                    y_lines=y_lines,
                    text_box=copy.deepcopy(sp_data.get("text_box", {})) if isinstance(sp_data.get("text_box"), dict) else {},
                    info_box=copy.deepcopy(sp_data.get("info_box", {})) if isinstance(sp_data.get("info_box"), dict) else {},
                    legend_visible=bool(sp_data.get("legend_visible", True)),
                    legend_position=sp_data.get("legend_position", "best"),
                    show_grid=bool(sp_data.get("show_grid", True)),
                ))
            figures.append(FigureModel(
                id=fig_data.get("id", new_id()),
                title=fig_data.get("title", "Figure"),
                rows=int(fig_data.get("rows", 1)),
                cols=int(fig_data.get("cols", 1)),
                subplots=subplots or [SubplotModel()],
            ))
        project = ProjectModel(
            name=data.get("name", "Untitled Project"),
            figures=figures or [FigureModel()],
            style=style,
            style_sheet=style_sheet,
            config_path=data.get("config_path", ""),
            signals_path=data.get("signals_path", ""),
            preview_csv_path=data.get("preview_csv_path", ""),
            selected_cylinder=data.get("selected_cylinder", "user_cylinder_1"),
            notes=data.get("notes", ""),
        )
        self._ensure_axis_defaults(project)
        return project

    def _ensure_axis_defaults(self, project: ProjectModel) -> None:
        for fig in project.figures:
            if not fig.subplots:
                fig.subplots = [SubplotModel()]
            for sp in fig.subplots:
                if not sp.y_axes:
                    sp.y_axes = [AxisModel(title="Y")]
                for ser in sp.series:
                    if not ser.axis_id:
                        ser.axis_id = sp.y_axes[0].id

    # ---------- helpers ----------
    def current_figure(self) -> FigureModel | None:
        idx = self.figure_list.currentRow()
        if idx < 0 or idx >= len(self.project.figures):
            return self.project.figures[0] if self.project.figures else None
        return self.project.figures[idx]

    def current_subplot(self) -> SubplotModel | None:
        fig = self.current_figure()
        if fig is None:
            return None
        idx = self.subplot_list.currentRow()
        if idx < 0 or idx >= len(fig.subplots):
            return fig.subplots[0] if fig.subplots else None
        return fig.subplots[idx]

    def current_axis(self) -> AxisModel | None:
        sp = self.current_subplot()
        if sp is None:
            return None
        idx = self.axis_list.currentRow()
        if idx < 0 or idx >= len(sp.y_axes):
            return sp.y_axes[0] if sp.y_axes else None
        return sp.y_axes[idx]

    def current_series(self) -> SeriesModel | None:
        sp = self.current_subplot()
        if sp is None:
            return None
        idx = self.series_list.currentRow()
        if idx < 0 or idx >= len(sp.series):
            return sp.series[0] if sp.series else None
        return sp.series[idx]

    def current_event(self) -> EventModel | None:
        sp = self.current_subplot()
        if sp is None:
            return None
        idx = self.event_list.currentRow()
        if idx < 0 or idx >= len(getattr(sp, "events", [])):
            return sp.events[0] if getattr(sp, "events", []) else None
        return sp.events[idx]

    def _event_is_auto(self, event: EventModel | None) -> bool:
        return bool(event is not None and str(getattr(event, "source", "manual") or "manual").strip().lower() == "config_auto")

    def _event_is_manual(self, event: EventModel | None) -> bool:
        return bool(event is not None and not self._event_is_auto(event))

    def _event_is_locked(self, event: EventModel | None) -> bool:
        return bool(event is not None and bool(getattr(event, "locked", False)))

    def _event_source_display(self, event: EventModel | None) -> str:
        if event is None:
            return "-"
        return "AUTO" if self._event_is_auto(event) else "MANUELL"

    def _event_display_text(self, event: EventModel, index: int) -> str:
        label = str(getattr(event, "label", "") or f"Event {index + 1}").strip()
        tag = "AUTO" if self._event_is_auto(event) else "MAN"
        etype = str(getattr(event, "event_type", "custom") or "custom").strip().lower()
        lock = " LOCK" if self._event_is_locked(event) else ""
        hidden = " HIDE" if not bool(getattr(event, "visible", True)) else ""
        return f"{index + 1}. [{tag}/{etype.upper()}{lock}{hidden}] {label} @ {compact(getattr(event, 'x', 0.0))}"

    def _selected_event_scope(self) -> str:
        if not hasattr(self, "event_auto_scope_combo"):
            return "all"
        return str(self.event_auto_scope_combo.currentData() or "all")

    def _event_matches_scope(self, event: EventModel | None, scope: str) -> bool:
        if event is None:
            return False
        if scope == "all":
            return True
        return str(getattr(event, "event_type", "custom") or "custom").strip().lower() == str(scope).strip().lower()

    def _auto_events_matching_scope(self, events: list[EventModel]) -> list[EventModel]:
        scope = self._selected_event_scope()
        return [event for event in events if self._event_is_auto(event) and self._event_matches_scope(event, scope)]

    def _update_event_buttons(self) -> None:
        sp = self.current_subplot()
        events = list(getattr(sp, "events", []) or []) if sp is not None else []
        current = self.current_event()
        auto_events = [e for e in events if self._event_is_auto(e)]
        all_locked = bool(auto_events) and all(self._event_is_locked(e) for e in auto_events)
        all_hidden = bool(auto_events) and all(not bool(getattr(e, "visible", True)) for e in auto_events)
        scoped_events = self._auto_events_matching_scope(events)
        all_scoped_locked = bool(scoped_events) and all(self._event_is_locked(e) for e in scoped_events)
        all_scoped_hidden = bool(scoped_events) and all(not bool(getattr(e, "visible", True)) for e in scoped_events)
        self.event_delete_auto_button.setEnabled(bool(auto_events))
        self.event_lock_auto_button.setEnabled(bool(auto_events))
        self.event_hide_auto_button.setEnabled(bool(auto_events))
        self.event_delete_auto_scope_button.setEnabled(bool(scoped_events))
        self.event_lock_auto_scope_button.setEnabled(bool(scoped_events))
        self.event_hide_auto_scope_button.setEnabled(bool(scoped_events))
        self.event_lock_auto_button.setText("Auto entsperren" if all_locked else "Auto sperren")
        self.event_hide_auto_button.setText("Auto einblenden" if all_hidden else "Auto ausblenden")
        self.event_lock_auto_scope_button.setText("Typ entsperren" if all_scoped_locked else "Typ sperren")
        self.event_hide_auto_scope_button.setText("Typ einblenden" if all_scoped_hidden else "Typ ausblenden")
        self.event_manual_to_auto_button.setEnabled(self._event_is_manual(current))
        self.event_delete_button.setEnabled(current is not None)
        self.event_up_button.setEnabled(current is not None)
        self.event_down_button.setEnabled(current is not None)

    def _figure_display_text(self, fig: FigureModel, index: int) -> str:
        return f"{index + 1}. {fig.title} [{fig.rows}x{fig.cols}]"

    def _subplot_display_text(self, sp: SubplotModel, index: int) -> str:
        return f"{index + 1}. {sp.title} ({sp.plot_type})"

    def _axis_display_text(self, axis: AxisModel, index: int) -> str:
        title = axis.title or f"Axis {index + 1}"
        return f"{index + 1}. {title} [{axis.side}, {compact(axis.spine_offset)}]"

    def _series_display_text(self, series: SeriesModel, index: int) -> str:
        label = series.label or series.signal_key
        return f"{index + 1}. {label}"

    def _clone_subplot_model(self, subplot: SubplotModel, *, title_suffix: str = " Copy") -> SubplotModel:
        clone = copy.deepcopy(subplot)
        clone.id = new_id()
        clone.title = f"{subplot.title}{title_suffix}" if title_suffix else str(subplot.title)
        axis_map: dict[str, str] = {}
        for axis in clone.y_axes:
            old_axis_id = axis.id
            axis.id = new_id()
            axis_map[old_axis_id] = axis.id
        for series in clone.series:
            series.id = new_id()
            if clone.y_axes:
                series.axis_id = axis_map.get(series.axis_id, clone.y_axes[0].id)
        for event in clone.events:
            event.id = new_id()
        return clone

    def subplot_index_by_id(self, figure: FigureModel | None, subplot_id: str) -> int:
        if figure is None:
            return -1
        for idx, subplot in enumerate(figure.subplots):
            if subplot.id == subplot_id:
                return idx
        return -1

    def _set_list_item_style(self, item: QListWidgetItem | None, *, selected: bool = False, drop_target: bool = False, accent: str = 'blue') -> None:
        if item is None:
            return
        font = item.font()
        font.setBold(bool(selected or drop_target))
        item.setFont(font)
        background = None
        if selected and drop_target:
            background = QColor('#ffe9a8')
        elif drop_target:
            background = QColor('#ffe7b3')
        elif selected and accent == 'green':
            background = QColor('#dff5e3')
        elif selected:
            background = QColor('#dbeafe')
        item.setBackground(QBrush(background) if background is not None else QBrush())

    def _update_project_selection_feedback(self) -> None:
        current_fig_row = self.figure_list.currentRow() if hasattr(self, 'figure_list') else -1
        current_subplot_row = self.subplot_list.currentRow() if hasattr(self, 'subplot_list') else -1
        drag_target_row = getattr(self, '_figure_drop_target_index', None)

        fig = self.current_figure()
        subplot = self.current_subplot()
        if hasattr(self, 'figure_selection_info'):
            self.figure_selection_info.setText(
                f"Aktive Figure: {self._figure_display_text(fig, current_fig_row)}" if fig is not None and current_fig_row >= 0 else 'Aktive Figure: –'
            )
        if hasattr(self, 'subplot_selection_info'):
            self.subplot_selection_info.setText(
                f"Aktiver Subplot: {self._subplot_display_text(subplot, current_subplot_row)}" if subplot is not None and current_subplot_row >= 0 else 'Aktiver Subplot: –'
            )

        if hasattr(self, 'figure_list'):
            for row in range(self.figure_list.count()):
                self._set_list_item_style(
                    self.figure_list.item(row),
                    selected=(row == current_fig_row),
                    drop_target=(drag_target_row is not None and row == int(drag_target_row)),
                    accent='blue',
                )
        if hasattr(self, 'subplot_list'):
            for row in range(self.subplot_list.count()):
                self._set_list_item_style(
                    self.subplot_list.item(row),
                    selected=(row == current_subplot_row),
                    drop_target=False,
                    accent='green',
                )

    def on_project_drag_feedback(self, message: str) -> None:
        if message:
            self.statusBar().showMessage(message)
        else:
            self.update_statusbar()
        self._update_project_selection_feedback()

    def on_project_drag_target_changed(self, figure_row: object) -> None:
        self._figure_drop_target_index = int(figure_row) if isinstance(figure_row, int) and figure_row >= 0 else None
        self._update_project_selection_feedback()

    def _select_subplot_in_figure(self, figure_index: int, subplot_id: str) -> None:
        if not (0 <= figure_index < len(self.project.figures)):
            return
        self.figure_list.setCurrentRow(figure_index)
        figure = self.project.figures[figure_index]
        subplot_index = self.subplot_index_by_id(figure, subplot_id)
        if subplot_index < 0:
            subplot_index = 0
        self.subplot_list.setCurrentRow(subplot_index)
        subplot_item = self.subplot_list.item(subplot_index)
        if subplot_item is not None:
            self.subplot_list.scrollToItem(subplot_item)
        figure_item = self.figure_list.item(figure_index)
        if figure_item is not None:
            self.figure_list.scrollToItem(figure_item)
        self._update_project_selection_feedback()

    def on_subplot_dropped_on_figure(self, source_figure_index: int, subplot_id: str, target_figure_index: int, copy_mode: bool) -> None:
        if not subplot_id:
            return
        if not (0 <= source_figure_index < len(self.project.figures) and 0 <= target_figure_index < len(self.project.figures)):
            return
        source_figure = self.project.figures[source_figure_index]
        target_figure = self.project.figures[target_figure_index]
        source_subplot_index = self.subplot_index_by_id(source_figure, subplot_id)
        if source_subplot_index < 0:
            return

        source_subplot = source_figure.subplots[source_subplot_index]
        if copy_mode:
            new_subplot = self._clone_subplot_model(source_subplot)
            target_figure.subplots.append(new_subplot)
            moved_subplot_id = new_subplot.id
            action_text = 'kopiert'
        else:
            if source_figure_index == target_figure_index:
                self.statusBar().showMessage('Subplot ist bereits in dieser Figure. Für eine Kopie Strg beim Ziehen gedrückt halten.', 3500)
                self._figure_drop_target_index = None
                self._update_project_selection_feedback()
                return
            moved_subplot = source_figure.subplots.pop(source_subplot_index)
            target_figure.subplots.append(moved_subplot)
            moved_subplot_id = moved_subplot.id
            if not source_figure.subplots:
                self._ensure_minimum_project()
            action_text = 'verschoben'

        self._figure_drop_target_index = None
        self.refresh_all()
        self._select_subplot_in_figure(target_figure_index, moved_subplot_id)
        target_label = self._figure_display_text(self.project.figures[target_figure_index], target_figure_index)
        self.statusBar().showMessage(f'Subplot {action_text}: {target_label}', 3500)
        self.set_dirty(f'Subplot {action_text}')

    def series_index_by_id(self, subplot: SubplotModel | None, series_id: str) -> int:
        if subplot is None:
            return -1
        for idx, series in enumerate(subplot.series):
            if series.id == series_id:
                return idx
        return -1

    def focus_series_from_preview(self, subplot_index: int, series_id: str) -> None:
        fig = self.current_figure()
        if fig is None or not (0 <= subplot_index < len(fig.subplots)):
            return
        self.inspector_dock.raise_()
        self.inspector_dock.show()
        self.inspector_tabs.setCurrentIndex(2)
        self.subplot_list.setCurrentRow(subplot_index)
        subplot = fig.subplots[subplot_index]
        series_index = self.series_index_by_id(subplot, series_id)
        if series_index < 0:
            return
        self.series_list.setCurrentRow(series_index)
        item = self.series_list.item(series_index)
        if item is not None:
            self.series_list.scrollToItem(item)
        self.refresh_series_editor()
        label = subplot.series[series_index].label or subplot.series[series_index].signal_key
        self.statusBar().showMessage(f"Inspector: Serie ausgewählt – {label}", 2500)

    def move_series_between_subplots(self, source_subplot_index: int, series_id: str, target_subplot_index: int) -> None:
        fig = self.current_figure()
        if fig is None:
            return
        if not (0 <= source_subplot_index < len(fig.subplots) and 0 <= target_subplot_index < len(fig.subplots)):
            return
        if source_subplot_index == target_subplot_index:
            return
        source_subplot = fig.subplots[source_subplot_index]
        target_subplot = fig.subplots[target_subplot_index]
        series_index = self.series_index_by_id(source_subplot, series_id)
        if series_index < 0:
            return
        series = source_subplot.series.pop(series_index)
        if target_subplot.y_axes:
            valid_axis_ids = {axis.id for axis in target_subplot.y_axes}
            if series.axis_id not in valid_axis_ids:
                series.axis_id = target_subplot.y_axes[0].id
        else:
            new_axis = AxisModel(title="Y", side="left", color=series.color or "#1f77b4")
            target_subplot.y_axes.append(new_axis)
            series.axis_id = new_axis.id
        target_subplot.series.append(series)
        self.refresh_all()
        self.subplot_list.setCurrentRow(target_subplot_index)
        new_index = self.series_index_by_id(target_subplot, series.id)
        if new_index >= 0:
            self.series_list.setCurrentRow(new_index)
            item = self.series_list.item(new_index)
            if item is not None:
                self.series_list.scrollToItem(item)
        self.inspector_tabs.setCurrentIndex(2)
        moved_label = series.label or series.signal_key
        self.set_dirty(f"Serie verschoben: {moved_label} → Subplot {target_subplot_index + 1}")

    def set_dirty(self, message: str = "") -> None:
        self.refresh_json_preview()
        self.render_preview()
        self.update_statusbar()
        if message:
            self.statusBar().showMessage(message, 2500)

    def on_project_meta_changed(self) -> None:
        if self.loading_ui:
            return
        self.project.name = self.project_name_edit.text().strip() or "Untitled Project"
        self.set_dirty("Projekt aktualisiert")
        self.refresh_lists()

    def on_notes_changed(self) -> None:
        if self.loading_ui:
            return
        self.project.notes = self.notes_edit.toPlainText()
        self.set_dirty()

    def on_figure_meta_changed(self) -> None:
        if self.loading_ui:
            return
        fig = self.current_figure()
        if fig is None:
            return
        fig.title = self.figure_title_edit.text().strip() or "Figure"
        self.set_dirty("Figure aktualisiert")
        self.refresh_lists()

    def on_figure_layout_changed(self) -> None:
        if self.loading_ui:
            return
        fig = self.current_figure()
        if fig is None:
            return
        fig.rows = self.figure_rows_spin.value()
        fig.cols = self.figure_cols_spin.value()
        self.set_dirty("Layout aktualisiert")
        self.refresh_lists()

    def on_subplot_meta_changed(self) -> None:
        if self.loading_ui:
            return
        sp = self.current_subplot()
        if sp is None:
            return
        sp.title = self.subplot_title_edit.text().strip() or "Subplot"
        sp.show_title = self.subplot_show_title_check.isChecked()
        sp.plot_type = self.subplot_type_combo.currentText()
        sp.x_signal = self.subplot_x_signal_edit.text().strip() or "theta_deg"
        sp.x_title = self.subplot_x_title_edit.text().strip() or "Theta"
        sp.x_unit_preset = self.subplot_x_unit_combo.currentText() or "raw"
        sp.x_scale_factor = self.subplot_x_scale_spin.value()
        sp.x_offset = self.subplot_x_offset_spin.value()
        sp.x_limit_mode = self.subplot_x_limit_mode_combo.currentText() or "data"
        sp.x_min = self.subplot_x_min_spin.value()
        sp.x_max = self.subplot_x_max_spin.value()
        sp.x_start_at_zero = self.subplot_x_start_zero_check.isChecked()
        sp.show_grid = self.subplot_grid_check.isChecked()
        sp.legend_visible = self.subplot_legend_check.isChecked()
        sp.legend_position = self.subplot_legend_pos_combo.currentText()
        self.set_dirty("Subplot aktualisiert")
        self.refresh_lists()

    def apply_x_range_preset(self, preset: str) -> None:
        sp = self.current_subplot()
        if sp is None:
            return
        self.loading_ui = True
        try:
            if preset == "auto":
                self.subplot_x_limit_mode_combo.setCurrentText("data")
            else:
                mapping = {
                    "0_360": (0.0, 360.0),
                    "0_720": (0.0, 720.0),
                    "pm180": (-180.0, 180.0),
                    "pm360": (-360.0, 360.0),
                }
                xmin, xmax = mapping.get(preset, (0.0, 720.0))
                self.subplot_x_limit_mode_combo.setCurrentText("manual")
                self.subplot_x_min_spin.setValue(xmin)
                self.subplot_x_max_spin.setValue(xmax)
        finally:
            self.loading_ui = False
        self.on_subplot_meta_changed()

    def reset_current_axis_to_auto(self) -> None:
        axis = self.current_axis()
        if axis is None:
            return
        self.loading_ui = True
        try:
            self.axis_limit_mode_combo.setCurrentText("data")
            self.axis_y_min_spin.setValue(0.0)
            self.axis_y_max_spin.setValue(1.0)
            self.axis_tick_step_spin.setValue(0.0)
            self.axis_minor_tick_step_spin.setValue(0.0)
            self.axis_major_grid_check.setChecked(True)
            self.axis_minor_grid_check.setChecked(False)
        finally:
            self.loading_ui = False
        self.on_axis_meta_changed()

    def swap_current_axis_side(self) -> None:
        axis = self.current_axis()
        if axis is None:
            return
        new_side = "right" if str(getattr(axis, "side", "left")) == "left" else "left"
        self.axis_side_combo.setCurrentText(new_side)

    def enable_current_axis_full_grid(self) -> None:
        axis = self.current_axis()
        if axis is None:
            return
        self.axis_major_grid_check.setChecked(True)
        self.axis_minor_grid_check.setChecked(True)
        if float(self.axis_tick_step_spin.value() or 0.0) <= 0.0:
            self.axis_tick_step_spin.setValue(1.0)
        if float(self.axis_minor_tick_step_spin.value() or 0.0) <= 0.0:
            self.axis_minor_tick_step_spin.setValue(max(0.2, self.axis_tick_step_spin.value() / 5.0))

    def _axis_style_payload(self, axis: AxisModel) -> dict[str, Any]:
        return {
            "color": str(getattr(axis, "color", "#1f77b4") or "#1f77b4"),
            "visible": bool(getattr(axis, "visible", True)),
            "limit_mode": str(getattr(axis, "limit_mode", "data") or "data"),
            "y_min": float(getattr(axis, "y_min", 0.0) or 0.0),
            "y_max": float(getattr(axis, "y_max", 1.0) or 1.0),
            "tick_step": float(getattr(axis, "tick_step", 0.0) or 0.0),
            "minor_tick_step": float(getattr(axis, "minor_tick_step", 0.0) or 0.0),
            "major_grid": bool(getattr(axis, "major_grid", True)),
            "minor_grid": bool(getattr(axis, "minor_grid", False)),
        }

    def _apply_axis_style_payload(self, axis: AxisModel, payload: dict[str, Any]) -> None:
        axis.color = str(payload.get("color", axis.color) or axis.color)
        axis.visible = bool(payload.get("visible", axis.visible))
        axis.limit_mode = str(payload.get("limit_mode", axis.limit_mode) or axis.limit_mode)
        axis.y_min = float(payload.get("y_min", axis.y_min) or axis.y_min)
        axis.y_max = float(payload.get("y_max", axis.y_max) or axis.y_max)
        axis.tick_step = float(payload.get("tick_step", axis.tick_step) or 0.0)
        axis.minor_tick_step = float(payload.get("minor_tick_step", axis.minor_tick_step) or 0.0)
        axis.major_grid = bool(payload.get("major_grid", axis.major_grid))
        axis.minor_grid = bool(payload.get("minor_grid", axis.minor_grid))

    def copy_current_axis_style(self) -> None:
        axis = self.current_axis()
        if axis is None:
            return
        self.axis_style_clipboard = self._axis_style_payload(axis)
        self.statusBar().showMessage("Achsenstil kopiert", 2000)

    def paste_current_axis_style(self) -> None:
        axis = self.current_axis()
        if axis is None or not self.axis_style_clipboard:
            return
        self._apply_axis_style_payload(axis, self.axis_style_clipboard)
        self.set_dirty("Achsenstil eingefügt")
        self.refresh_axes()
        self.render_preview()
        self.statusBar().showMessage("Achsenstil eingefügt", 2000)

    def apply_current_axis_style_to_subplot(self) -> None:
        axis = self.current_axis()
        subplot = self.current_subplot()
        if axis is None or subplot is None:
            return
        payload = self._axis_style_payload(axis)
        changed = 0
        for target in list(getattr(subplot, "y_axes", []) or []):
            self._apply_axis_style_payload(target, payload)
            changed += 1
        if changed <= 0:
            return
        self.set_dirty("Achsenstil auf Subplot angewendet")
        self.refresh_axes()
        self.render_preview()
        self.statusBar().showMessage(f"Achsenstil auf {changed} Achsen im Subplot angewendet", 2500)

    def apply_current_axis_style_to_all_subplots(self) -> None:
        axis = self.current_axis()
        if axis is None:
            return
        payload = self._axis_style_payload(axis)
        changed = 0
        for fig in list(getattr(self.project, "figures", []) or []):
            for subplot in list(getattr(fig, "subplots", []) or []):
                for target in list(getattr(subplot, "y_axes", []) or []):
                    self._apply_axis_style_payload(target, payload)
                    changed += 1
        if changed <= 0:
            return
        self.set_dirty("Achsenstil auf alle Subplots angewendet")
        self.refresh_axes()
        self.render_preview()
        self.statusBar().showMessage(f"Achsenstil auf {changed} Achsen in allen Subplots angewendet", 3000)

    def _nice_number(self, value: float, round_result: bool = True) -> float:
        if not math.isfinite(value) or value <= 0.0:
            return 1.0
        exponent = math.floor(math.log10(value))
        fraction = value / (10.0 ** exponent)
        if round_result:
            if fraction < 1.5:
                nice_fraction = 1.0
            elif fraction < 3.0:
                nice_fraction = 2.0
            elif fraction < 7.0:
                nice_fraction = 5.0
            else:
                nice_fraction = 10.0
        else:
            if fraction <= 1.0:
                nice_fraction = 1.0
            elif fraction <= 2.0:
                nice_fraction = 2.0
            elif fraction <= 5.0:
                nice_fraction = 5.0
            else:
                nice_fraction = 10.0
        return nice_fraction * (10.0 ** exponent)

    def _nice_axis_limits(self, values: list[float]) -> tuple[float, float, float, float] | None:
        numeric = [float(v) for v in values if isinstance(v, (int, float)) and math.isfinite(float(v))]
        if not numeric:
            return None
        vmin = min(numeric)
        vmax = max(numeric)
        if math.isclose(vmin, vmax, rel_tol=1e-12, abs_tol=1e-12):
            pad = self._nice_number(max(abs(vmin), 1.0) * 0.1, round_result=False)
            vmin -= pad
            vmax += pad
        raw_range = max(vmax - vmin, 1e-12)
        nice_range = self._nice_number(raw_range, round_result=False)
        major_step = self._nice_number(nice_range / 6.0, round_result=True)
        y_min = math.floor(vmin / major_step) * major_step
        y_max = math.ceil(vmax / major_step) * major_step
        if math.isclose(y_min, y_max, rel_tol=1e-12, abs_tol=1e-12):
            y_max = y_min + major_step
        minor_step = major_step / 5.0
        return y_min, y_max, major_step, minor_step

    def _collect_axis_preview_values(self, subplot: SubplotModel, axis: AxisModel) -> list[float]:
        out: list[float] = []
        for series in list(getattr(subplot, "series", []) or []):
            if not bool(getattr(series, "visible", True)):
                continue
            if str(getattr(series, "axis_id", "") or "") != str(getattr(axis, "id", "") or ""):
                continue
            y_values, _why = self.resolve_series_values(series.signal_key)
            if y_values is None:
                continue
            transformed = transform_values(y_values, getattr(series, "unit_preset", "raw"), getattr(series, "scale_factor", 1.0), getattr(series, "offset", 0.0)) or []
            for value in transformed:
                try:
                    fv = float(value)
                except Exception:
                    continue
                if math.isfinite(fv):
                    out.append(fv)
        return out

    def fit_current_axis_to_data_nice(self) -> None:
        axis = self.current_axis()
        subplot = self.current_subplot()
        if axis is None or subplot is None:
            return
        values = self._collect_axis_preview_values(subplot, axis)
        fit = self._nice_axis_limits(values)
        if fit is None:
            self.statusBar().showMessage("Auto-Limits: keine numerischen Preview-Daten für diese Achse", 3000)
            return
        y_min, y_max, major_step, minor_step = fit
        self.loading_ui = True
        try:
            self.axis_limit_mode_combo.setCurrentText("manual")
            self.axis_y_min_spin.setValue(y_min)
            self.axis_y_max_spin.setValue(y_max)
            self.axis_tick_step_spin.setValue(major_step)
            self.axis_minor_tick_step_spin.setValue(minor_step)
            self.axis_major_grid_check.setChecked(True)
            self.axis_minor_grid_check.setChecked(True)
        finally:
            self.loading_ui = False
        self.on_axis_meta_changed()
        self.statusBar().showMessage(f"Auto-Limits gesetzt: {compact(y_min)} … {compact(y_max)}", 3000)

    def _selected_list_row_by_id(self, list_widget: QListWidget) -> tuple[int, str]:
        row = list_widget.currentRow()
        item = list_widget.currentItem()
        selected_id = str(item.data(Qt.UserRole)) if item is not None and item.data(Qt.UserRole) is not None else ""
        return row, selected_id

    def _restore_list_row_by_id(self, list_widget: QListWidget, preferred_row: int, preferred_id: str) -> None:
        row = -1
        if preferred_id:
            for idx in range(list_widget.count()):
                item = list_widget.item(idx)
                if item is not None and str(item.data(Qt.UserRole) or "") == preferred_id:
                    row = idx
                    break
        if row < 0 and list_widget.count() > 0:
            row = min(max(preferred_row, 0), list_widget.count() - 1)
        if row >= 0:
            list_widget.setCurrentRow(row)
            item = list_widget.item(row)
            if item is not None:
                list_widget.scrollToItem(item)

    def _apply_axis_view_config(self, mpl_axis, axis_model: AxisModel) -> None:
        limit_mode = str(getattr(axis_model, "limit_mode", "data") or "data")
        if limit_mode == "manual":
            y_min = float(getattr(axis_model, "y_min", 0.0) or 0.0)
            y_max = float(getattr(axis_model, "y_max", 1.0) or 1.0)
            if y_max == y_min:
                y_max = y_min + 1.0
            mpl_axis.set_ylim(y_min, y_max)
        tick_step = float(getattr(axis_model, "tick_step", 0.0) or 0.0)
        minor_tick_step = float(getattr(axis_model, "minor_tick_step", 0.0) or 0.0)
        if tick_step > 0.0:
            mpl_axis.yaxis.set_major_locator(MultipleLocator(tick_step))
        if minor_tick_step > 0.0:
            mpl_axis.yaxis.set_minor_locator(MultipleLocator(minor_tick_step))
        axis_color = getattr(axis_model, "color", self.project.style.text_color) or self.project.style.text_color
        if bool(getattr(axis_model, "major_grid", True)):
            mpl_axis.grid(True, which="major", axis="y", color=self.project.style.grid_color, alpha=max(self.project.style.grid_alpha, 0.35))
        if bool(getattr(axis_model, "minor_grid", False)):
            mpl_axis.grid(True, which="minor", axis="y", color=self.project.style.grid_color, alpha=min(self.project.style.grid_alpha, 0.22))
        mpl_axis.tick_params(axis="y", colors=axis_color, labelsize=self.project.style.tick_label_size)

    def on_axis_meta_changed(self, *_args: Any) -> None:
        if self.loading_ui:
            return
        axis = self.current_axis()
        if axis is None:
            return
        axis.title = self.axis_title_edit.text().strip()
        axis.side = self.axis_side_combo.currentText()
        axis.spine_offset = self.axis_offset_spin.value()
        axis.color = self.axis_color_button.color()
        axis.visible = self.axis_visible_check.isChecked()
        axis.limit_mode = self.axis_limit_mode_combo.currentText() or "data"
        axis.y_min = self.axis_y_min_spin.value()
        axis.y_max = self.axis_y_max_spin.value()
        axis.tick_step = self.axis_tick_step_spin.value()
        axis.minor_tick_step = self.axis_minor_tick_step_spin.value()
        axis.major_grid = self.axis_major_grid_check.isChecked()
        axis.minor_grid = self.axis_minor_grid_check.isChecked()
        self.set_dirty("Achse aktualisiert")
        self.refresh_axes()
        self.refresh_series_axis_combo()

    def on_series_meta_changed(self, *_args: Any) -> None:
        if self.loading_ui:
            return
        series = self.current_series()
        if series is None:
            return
        series.signal_key = self.series_signal_edit.text().strip() or "p_cyl_pa"
        series.label = self.series_label_edit.text().strip()
        series.axis_id = self.series_axis_combo.currentData() or series.axis_id
        series.series_type = self.series_type_combo.currentText()
        series.visible = self.series_visible_check.isChecked()
        series.color = self.series_color_button.color()
        series.line_style = self.series_line_style_combo.currentText()
        series.marker = self.series_marker_combo.currentText()
        series.line_width = self.series_line_width_spin.value()
        series.marker_size = self.series_marker_size_spin.value()
        series.unit_preset = self.series_unit_combo.currentText() or "raw"
        series.scale_factor = self.series_scale_spin.value()
        series.offset = self.series_offset_spin.value()
        self.set_dirty("Serie aktualisiert")
        self.refresh_series()

    def on_cylinder_changed(self, text: str) -> None:
        if self.loading_ui:
            return
        self.project.selected_cylinder = text.strip() or "user_cylinder_1"
        self.catalog.selected_cylinder = self.project.selected_cylinder
        self.populate_signal_tree()
        self.update_diagnosis()
        self.set_dirty("Zylinder gewechselt")

    def refresh_all(self) -> None:
        self.loading_ui = True
        try:
            self.refresh_lists()
            self.populate_signal_tree()
            self.refresh_subplot_tab()
            self.refresh_axes()
            self.refresh_series()
            self.refresh_events()
            self.notes_edit.setPlainText(self.project.notes)
            self.refresh_json_preview()
            self.update_diagnosis()
            self.render_preview()
            self.update_statusbar()
        finally:
            self.loading_ui = False

    def refresh_lists(self) -> None:
        fig_index = max(0, self.figure_list.currentRow())
        sp_index = max(0, self.subplot_list.currentRow())
        self.figure_list.blockSignals(True)
        self.figure_list.clear()
        for idx, fig in enumerate(self.project.figures):
            item = QListWidgetItem(self._figure_display_text(fig, idx))
            item.setData(Qt.UserRole, fig.id)
            self.figure_list.addItem(item)
        if self.project.figures:
            self.figure_list.setCurrentRow(min(fig_index, len(self.project.figures) - 1))
        self.figure_list.blockSignals(False)

        fig = self.current_figure()
        current_figure_index = self.figure_list.currentRow()
        self.subplot_list.blockSignals(True)
        self.subplot_list.clear()
        if fig:
            for idx, sp in enumerate(fig.subplots):
                item = QListWidgetItem(self._subplot_display_text(sp, idx))
                item.setData(Qt.UserRole, sp.id)
                item.setData(Qt.UserRole + 1, current_figure_index)
                self.subplot_list.addItem(item)
            if fig.subplots:
                self.subplot_list.setCurrentRow(min(sp_index, len(fig.subplots) - 1))
        self.subplot_list.blockSignals(False)

        self.project_name_edit.setText(self.project.name)
        if fig:
            self.figure_title_edit.setText(fig.title)
            self.figure_rows_spin.setValue(fig.rows)
            self.figure_cols_spin.setValue(fig.cols)
        self.refresh_cylinder_combo()
        self._update_project_selection_feedback()

    def refresh_cylinder_combo(self) -> None:
        cyls = self.detected_cylinders() or self.detected_cylinders_from_preview() or [self.project.selected_cylinder or "user_cylinder_1"]
        current = self.project.selected_cylinder or cyls[0]
        if current not in cyls and cyls:
            current = cyls[0]
            self.project.selected_cylinder = current
        self.cylinder_combo.blockSignals(True)
        self.cylinder_combo.clear()
        self.cylinder_combo.addItems(cyls)
        if self.cylinder_combo.findText(current) < 0:
            self.cylinder_combo.addItem(current)
        self.cylinder_combo.setCurrentText(current)
        self.cylinder_combo.blockSignals(False)
        self.catalog.selected_cylinder = current

    def refresh_subplot_tab(self) -> None:
        sp = self.current_subplot()
        if sp is None:
            return
        self.subplot_title_edit.setText(sp.title)
        self.subplot_show_title_check.setChecked(getattr(sp, "show_title", True))
        self.subplot_type_combo.setCurrentText(sp.plot_type)
        self.subplot_x_signal_edit.setText(sp.x_signal)
        self.subplot_x_title_edit.setText(sp.x_title)
        self.subplot_x_unit_combo.setCurrentText(getattr(sp, "x_unit_preset", "raw"))
        self.subplot_x_scale_spin.setValue(getattr(sp, "x_scale_factor", 1.0))
        self.subplot_x_offset_spin.setValue(getattr(sp, "x_offset", 0.0))
        self.subplot_x_limit_mode_combo.setCurrentText(getattr(sp, "x_limit_mode", "data"))
        self.subplot_x_min_spin.setValue(getattr(sp, "x_min", 0.0))
        self.subplot_x_max_spin.setValue(getattr(sp, "x_max", 720.0))
        self.subplot_x_start_zero_check.setChecked(getattr(sp, "x_start_at_zero", True))
        self.subplot_grid_check.setChecked(sp.show_grid)
        self.subplot_legend_check.setChecked(sp.legend_visible)
        self.subplot_legend_pos_combo.setCurrentText(sp.legend_position)

    def refresh_axes(self) -> None:
        sp = self.current_subplot()
        previous_row, previous_id = self._selected_list_row_by_id(self.axis_list)
        self.axis_list.blockSignals(True)
        self.axis_list.clear()
        if sp:
            for idx, axis in enumerate(sp.y_axes):
                item = QListWidgetItem(self._axis_display_text(axis, idx))
                item.setData(Qt.UserRole, axis.id)
                self.axis_list.addItem(item)
            self._restore_list_row_by_id(self.axis_list, previous_row, previous_id)
        self.axis_list.blockSignals(False)
        self.refresh_axis_editor()
        self.refresh_series_axis_combo()

    def refresh_axis_editor(self) -> None:
        axis = self.current_axis()
        self.loading_ui = True
        try:
            if axis is None:
                self.axis_title_edit.setText("")
                self.axis_side_combo.setCurrentText("left")
                self.axis_offset_spin.setValue(0.0)
                self.axis_color_button.setColor("#1f77b4")
                self.axis_visible_check.setChecked(True)
                self.axis_limit_mode_combo.setCurrentText("data")
                self.axis_y_min_spin.setValue(0.0)
                self.axis_y_max_spin.setValue(1.0)
                self.axis_tick_step_spin.setValue(0.0)
                self.axis_minor_tick_step_spin.setValue(0.0)
                self.axis_major_grid_check.setChecked(True)
                self.axis_minor_grid_check.setChecked(False)
            else:
                self.axis_title_edit.setText(axis.title)
                self.axis_side_combo.setCurrentText(axis.side)
                self.axis_offset_spin.setValue(axis.spine_offset)
                self.axis_color_button.setColor(axis.color)
                self.axis_visible_check.setChecked(axis.visible)
                self.axis_limit_mode_combo.setCurrentText(getattr(axis, "limit_mode", "data"))
                self.axis_y_min_spin.setValue(getattr(axis, "y_min", 0.0))
                self.axis_y_max_spin.setValue(getattr(axis, "y_max", 1.0))
                self.axis_tick_step_spin.setValue(getattr(axis, "tick_step", 0.0))
                self.axis_minor_tick_step_spin.setValue(getattr(axis, "minor_tick_step", 0.0))
                self.axis_major_grid_check.setChecked(bool(getattr(axis, "major_grid", True)))
                self.axis_minor_grid_check.setChecked(bool(getattr(axis, "minor_grid", False)))
        finally:
            self.loading_ui = False

    def refresh_series(self) -> None:
        sp = self.current_subplot()
        previous_row, previous_id = self._selected_list_row_by_id(self.series_list)
        self.series_list.blockSignals(True)
        self.series_list.clear()
        if sp:
            for idx, ser in enumerate(sp.series):
                item = QListWidgetItem(self._series_display_text(ser, idx))
                item.setData(Qt.UserRole, ser.id)
                self.series_list.addItem(item)
            self._restore_list_row_by_id(self.series_list, previous_row, previous_id)
        self.series_list.blockSignals(False)
        self.refresh_series_editor()

    def refresh_events(self) -> None:
        sp = self.current_subplot()
        previous_row, previous_id = self._selected_list_row_by_id(self.event_list)
        self.event_list.blockSignals(True)
        self.event_list.clear()
        if sp:
            for idx, event in enumerate(getattr(sp, "events", [])):
                item = QListWidgetItem(self._event_display_text(event, idx))
                item.setData(Qt.UserRole, event.id)
                self.event_list.addItem(item)
            self._restore_list_row_by_id(self.event_list, previous_row, previous_id)
        self.event_list.blockSignals(False)
        self.refresh_event_editor()
        self._update_event_buttons()

    def refresh_series_axis_combo(self) -> None:
        sp = self.current_subplot()
        current_axis_id = self.current_series().axis_id if self.current_series() else ""
        self.series_axis_combo.blockSignals(True)
        self.series_axis_combo.clear()
        if sp:
            for idx, axis in enumerate(sp.y_axes):
                self.series_axis_combo.addItem(self._axis_display_text(axis, idx), axis.id)
            i = self.series_axis_combo.findData(current_axis_id)
            if i >= 0:
                self.series_axis_combo.setCurrentIndex(i)
        self.series_axis_combo.blockSignals(False)

    def refresh_series_editor(self) -> None:
        ser = self.current_series()
        self.loading_ui = True
        try:
            if ser is None:
                self.series_signal_edit.setText("")
                self.series_label_edit.setText("")
                self.series_type_combo.setCurrentText("line")
                self.series_visible_check.setChecked(True)
                self.series_color_button.setColor("#1f77b4")
                self.series_line_style_combo.setCurrentText("-")
                self.series_marker_combo.setCurrentText("")
                self.series_line_width_spin.setValue(self.project.style.default_line_width)
                self.series_marker_size_spin.setValue(self.project.style.default_marker_size)
                self.series_unit_combo.setCurrentText("raw")
                self.series_scale_spin.setValue(1.0)
                self.series_offset_spin.setValue(0.0)
            else:
                self.series_signal_edit.setText(ser.signal_key)
                self.series_label_edit.setText(ser.label)
                self.series_type_combo.setCurrentText(ser.series_type)
                self.series_visible_check.setChecked(ser.visible)
                self.series_color_button.setColor(ser.color)
                self.series_line_style_combo.setCurrentText(ser.line_style)
                self.series_marker_combo.setCurrentText(ser.marker)
                self.series_line_width_spin.setValue(ser.line_width)
                self.series_marker_size_spin.setValue(ser.marker_size)
                self.series_unit_combo.setCurrentText(getattr(ser, "unit_preset", "raw"))
                self.series_scale_spin.setValue(ser.scale_factor)
                self.series_offset_spin.setValue(ser.offset)
                self.refresh_series_axis_combo()
                i = self.series_axis_combo.findData(ser.axis_id)
                if i >= 0:
                    self.series_axis_combo.setCurrentIndex(i)
        finally:
            self.loading_ui = False

    def refresh_event_editor(self) -> None:
        event = self.current_event()
        self.loading_ui = True
        try:
            if event is None:
                self.event_label_edit.setText("")
                self.event_source_label.setText("-")
                self.event_locked_label.setText("-")
                self.event_source_note_label.setText("")
                self.event_type_combo.setCurrentText("custom")
                self.event_x_spin.setValue(0.0)
                self.event_visible_check.setChecked(True)
                self.event_show_label_check.setChecked(True)
                self.event_color_button.setColor("#666666")
                self.event_line_style_combo.setCurrentText(":")
                self.event_line_width_spin.setValue(1.0)
                self.event_alpha_spin.setValue(0.9)
                self.event_label_rotation_spin.setValue(90.0)
                self.event_label_font_size_spin.setValue(max(7, self.project.style.font_size - 2))
                self.event_label_bg_color_button.setColor(self.project.style.axes_facecolor)
                self.event_label_bg_alpha_spin.setValue(0.8)
                self.event_label_border_color_button.setColor("#ffffff")
                self.event_label_y_spin.setValue(0.98)
                self.event_label_ha_combo.setCurrentText("right")
                self.event_label_va_combo.setCurrentText("top")
            else:
                self.event_label_edit.setText(str(getattr(event, "label", "") or ""))
                self.event_source_label.setText(self._event_source_display(event))
                self.event_locked_label.setText("gesperrt" if self._event_is_locked(event) else "frei")
                self.event_source_note_label.setText(str(getattr(event, "source_note", "") or ""))
                self.event_type_combo.setCurrentText(str(getattr(event, "event_type", "custom") or "custom"))
                self.event_x_spin.setValue(float(getattr(event, "x", 0.0) or 0.0))
                self.event_visible_check.setChecked(bool(getattr(event, "visible", True)))
                self.event_show_label_check.setChecked(bool(getattr(event, "show_label", True)))
                self.event_color_button.setColor(str(getattr(event, "color", "#666666") or "#666666"))
                self.event_line_style_combo.setCurrentText(str(getattr(event, "line_style", ":") or ":"))
                self.event_line_width_spin.setValue(float(getattr(event, "line_width", 1.0) or 1.0))
                self.event_alpha_spin.setValue(float(getattr(event, "alpha", 0.9) or 0.9))
                self.event_label_rotation_spin.setValue(float(getattr(event, "label_rotation", 90.0) or 90.0))
                self.event_label_font_size_spin.setValue(float(getattr(event, "label_font_size", max(7, self.project.style.font_size - 2)) or max(7, self.project.style.font_size - 2)))
                self.event_label_bg_color_button.setColor(str(getattr(event, "label_bg_color", self.project.style.axes_facecolor) or self.project.style.axes_facecolor))
                self.event_label_bg_alpha_spin.setValue(float(getattr(event, "label_bg_alpha", 0.8) or 0.8))
                self.event_label_border_color_button.setColor(str(getattr(event, "label_border_color", "#ffffff") or "#ffffff"))
                self.event_label_y_spin.setValue(float(getattr(event, "label_y", 0.98) or 0.98))
                self.event_label_ha_combo.setCurrentText(str(getattr(event, "label_ha", "right") or "right"))
                self.event_label_va_combo.setCurrentText(str(getattr(event, "label_va", "top") or "top"))
            for widget in [self.event_label_edit, self.event_type_combo, self.event_x_spin, self.event_visible_check, self.event_show_label_check, self.event_color_button, self.event_line_style_combo, self.event_line_width_spin, self.event_alpha_spin, self.event_label_rotation_spin, self.event_label_font_size_spin, self.event_label_bg_color_button, self.event_label_bg_alpha_spin, self.event_label_border_color_button, self.event_label_y_spin, self.event_label_ha_combo, self.event_label_va_combo]:
                try:
                    widget.setEnabled(event is not None and not self._event_is_locked(event))
                except Exception:
                    pass
        finally:
            self.loading_ui = False
        self._update_event_buttons()

    def selected_config_cylinder_name(self) -> str:
        cfg = self.config_data if isinstance(self.config_data, dict) else {}
        selected = str(getattr(self.project, "selected_cylinder", "") or "").strip()
        if selected:
            return selected
        for volume in cfg.get("preprocessing", {}).get("volumes", []) if isinstance(cfg.get("preprocessing", {}), dict) else []:
            if isinstance(volume, dict) and str(volume.get("type", "")).strip().lower() == "cylinder":
                name = str(volume.get("name", "")).strip()
                if name:
                    return name
        return "cylinder"

    def generated_events_from_config(self) -> list[EventModel]:
        return _plot_plot_generate_events_from_config(self.config_data, self.project.config_path, self.selected_config_cylinder_name())

    def _replace_events_in_subplot(self, subplot: SubplotModel, events: list[EventModel]) -> None:
        subplot.events = [copy.deepcopy(event) for event in events]

    def _merge_generated_events_into_subplot(self, subplot: SubplotModel, events: list[EventModel]) -> bool:
        existing = list(getattr(subplot, "events", []) or [])
        manual_events = [copy.deepcopy(event) for event in existing if str(getattr(event, "source", "manual") or "manual").strip().lower() != "config_auto"]
        auto_events: list[EventModel] = []
        seen: set[tuple[str, int]] = set()
        for event in manual_events:
            key = (str(getattr(event, "label", "") or "").strip().lower(), int(round(float(getattr(event, "x", 0.0) or 0.0) * 1000.0)))
            seen.add(key)
        for event in events:
            clone = copy.deepcopy(event)
            key = (str(getattr(clone, "label", "") or "").strip().lower(), int(round(float(getattr(clone, "x", 0.0) or 0.0) * 1000.0)))
            if key in seen:
                continue
            seen.add(key)
            auto_events.append(clone)
        new_events = manual_events + auto_events
        before = [asdict(e) for e in existing]
        after = [asdict(e) for e in new_events]
        subplot.events = new_events
        return before != after

    def _autofill_events_from_config(self, overwrite: bool = False, scope: str = "all") -> int:
        events = self.generated_events_from_config()
        if not events:
            return 0
        changed = 0
        figures = self.project.figures if scope == "all" else ([self.current_figure()] if self.current_figure() is not None else [])
        for fig in figures:
            if fig is None:
                continue
            for subplot in fig.subplots:
                if overwrite:
                    if self._merge_generated_events_into_subplot(subplot, events):
                        changed += 1
                elif not getattr(subplot, "events", []):
                    self._replace_events_in_subplot(subplot, events)
                    changed += 1
        return changed

    def regenerate_events_from_config_for_current_subplot(self) -> None:
        subplot = self.current_subplot()
        if subplot is None:
            return
        events = self.generated_events_from_config()
        if not events:
            self.statusBar().showMessage("Keine Events aus der aktiven Config ableitbar", 3000)
            return
        self._merge_generated_events_into_subplot(subplot, events)
        self.refresh_events()
        self.set_dirty("Auto-Events aus Config für aktuellen Subplot aktualisiert (manuelle Events beibehalten)")

    def regenerate_events_from_config_for_all_subplots(self) -> None:
        changed = self._autofill_events_from_config(overwrite=True, scope="all")
        if changed <= 0:
            self.statusBar().showMessage("Keine Events aus der aktiven Config ableitbar", 3000)
            return
        self.refresh_events()
        self.set_dirty(f"Auto-Events aus Config für {changed} Subplots aktualisiert (manuelle Events beibehalten)")

    def update_statusbar(self) -> None:
        status_attrs = ('status_project', 'status_config', 'status_signals', 'status_csv', 'status_detect')
        if not all(hasattr(self, attr) and getattr(self, attr) is not None for attr in status_attrs):
            return
        self.status_project.setText(f"Project: {self.project.name}")
        self.status_config.setText(f"Config: {Path(self.project.config_path).name if self.project.config_path else '-'}")
        self.status_signals.setText(f"Signals: {Path(self.project.signals_path).name if self.project.signals_path else '-'}")
        csv_name = Path(self.project.preview_csv_path).name if self.project.preview_csv_path else '-'
        requested_path = str(getattr(self, '_preview_csv_requested_path', '') or '')
        resolved_path = str(getattr(self, '_preview_csv_resolved_path', '') or self.project.preview_csv_path or '')
        reason = str(getattr(self, '_preview_csv_resolution_reason', '') or '')
        if requested_path and resolved_path and Path(requested_path) != Path(resolved_path):
            csv_status = f"CSV: {csv_name} [uniform]"
            self.status_csv.setToolTip(f"Aktiv: {resolved_path}\nAngefordert: {requested_path}\nRegel: {reason}")
        else:
            csv_status = f"CSV: {csv_name}"
            self.status_csv.setToolTip(resolved_path or csv_name)
        self.status_csv.setText(csv_status)
        cycle = self.diagnosis.get("cycle_type", "-")
        mode = self.diagnosis.get("gasexchange_mode", "-")
        signal_mode = self.diagnosis.get("signal_mode", "-")
        self.status_detect.setText(f"Detected: {cycle} | {mode} | {signal_mode}")

    # ---------- diagnosis ----------
    def detected_cylinders_from_preview(self) -> list[str]:
        patterns = [
            r"(user_cylinder_\d+)",
            r"(cylinder_\d+)",
            r"(cyl_?\d+)",
        ]
        found: list[str] = []
        for header in self.preview_csv.headers:
            for pattern in patterns:
                m = re.search(pattern, header, flags=re.IGNORECASE)
                if m:
                    name = m.group(1)
                    if name not in found:
                        found.append(name)
        return found

    def detected_cylinders(self) -> list[str]:
        out: list[str] = []
        for cyl in self.config_data.get("user_cylinders", []) if isinstance(self.config_data, dict) else []:
            if isinstance(cyl, dict) and cyl.get("name"):
                if cyl.get("enabled", True):
                    out.append(str(cyl.get("name")))
        return out

    def detect_config_info(self) -> dict[str, Any]:
        cfg = self.config_data if isinstance(self.config_data, dict) else {}
        cycle_raw = self._get_nested_value(
            cfg,
            ("engine", "cycle_type"),
            ("engine", "cycle"),
            ("cycle_type",),
            ("cycle",),
        )
        gas_mode_raw = self._get_nested_value(
            cfg,
            ("gasexchange", "mode"),
            ("gasexchange", "gasexchange_mode"),
            ("gasexchange", "type"),
            ("mode",),
        )
        signal_mode_raw = self._get_nested_value(
            cfg,
            ("simulation", "signal_mode"),
            ("simulation", "signals", "mode"),
            ("numerics", "signal_mode"),
            ("numerics", "state_representation"),
            ("signal_mode",),
        )
        preview_source = str(self._get_nested_value(cfg, ("gasexchange", "preview_source"), ("preview_source",)) or "unknown")
        cycle_type = self._normalize_cycle_type(cycle_raw)
        gas_mode = self._normalize_gasexchange_mode(gas_mode_raw)
        signal_mode = self._normalize_signal_mode(signal_mode_raw)
        cylinders = self.detected_cylinders()
        active_cylinder = str(
            self._get_nested_value(cfg, ("active_user_cylinder",), ("simulation", "active_user_cylinder"))
            or (cylinders[0] if cylinders else self.project.selected_cylinder)
        )
        validation = {
            "config_loaded": bool(cfg),
            "signals_loaded": bool(self.catalog.raw),
            "preview_csv_loaded": bool(self.preview_csv.path),
            "preview_csv_error": self.preview_csv.error,
            "signals_error": self.catalog.error,
            "signals_path_valid": not self.project.signals_path or Path(self.project.signals_path).name in ALLOWED_SIGNAL_FILE_BASENAMES,
        }
        return {
            "cycle_type": cycle_type,
            "gasexchange_mode": gas_mode,
            "signal_mode": signal_mode,
            "preview_source": preview_source,
            "active_cylinder": active_cylinder,
            "cylinders": cylinders,
            "validation": validation,
        }

    def update_diagnosis(self) -> None:
        self.diagnosis = self.detect_config_info()
        lines = [
            f"cycle_type: {self.diagnosis.get('cycle_type', '-')}",
            f"gasexchange_mode: {self.diagnosis.get('gasexchange_mode', '-')}",
            f"signal_mode: {self.diagnosis.get('signal_mode', '-')}",
            f"preview_source: {self.diagnosis.get('preview_source', '-')}",
            f"active_cylinder: {self.diagnosis.get('active_cylinder', '-')}",
            f"cylinders: {', '.join(self.diagnosis.get('cylinders', [])) or '-'}",
            "",
            "validation:",
        ]
        for k, v in (self.diagnosis.get("validation", {}) or {}).items():
            lines.append(f"  {k}: {v}")
        if self.preview_csv.headers:
            lines.extend(["", f"preview_csv_columns: {len(self.preview_csv.headers)}", ", ".join(self.preview_csv.headers[:60])])
        if self.catalog.raw:
            lines.extend(["", "signal_groups:"])
            for key, label in self.catalog.groups():
                lines.append(f"  {label}: {len(self.catalog.raw.get(key, []))}")
        self.diagnosis_text.setPlainText("\n".join(lines))
        self.update_statusbar()

    # ---------- loading/saving files ----------
    def new_project(self) -> None:
        self.project = ProjectModel(style=StyleModel.preset("Light Engineering"))
        self.current_project_path = None
        self._ensure_minimum_project()
        self._store_plot_style_state()
        self.refresh_all()
        self.statusBar().showMessage("Neues Projekt erstellt", 2000)

    def open_project(self) -> None:
        path, _ = get_open_file_name(self, "Projekt öffnen", str(Path.cwd()), "YAML/JSON (*.yaml *.yml *.json)")
        if path:
            self.load_project_from_path(Path(path))

    def load_project_from_path(self, path: Path, silent: bool = False) -> None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                if path.suffix.lower() in {".yaml", ".yml"}:
                    data = yaml.safe_load(handle) or {}
                else:
                    data = json.load(handle)
            self.project = self.project_from_dict(data if isinstance(data, dict) else {})
            self.current_project_path = path
            if self.project.signals_path:
                self.load_signals_from_path(Path(self.project.signals_path), silent=True)
            if self.project.config_path:
                self.load_config_from_path(Path(self.project.config_path), silent=True)
            if self.project.preview_csv_path:
                self.load_preview_csv_from_path(Path(self.project.preview_csv_path), silent=True)
            self._ensure_minimum_project()
            self._store_plot_style_state()
            self.refresh_all()
            self.settings.setValue("session/current_project_path", str(path))
            if not silent:
                self.statusBar().showMessage(f"Projekt geladen: {path}", 3000)
        except Exception as exc:
            show_critical(self, "Projekt laden", str(exc))

    def save_project(self) -> None:
        if self.current_project_path is None:
            self.save_project_as()
            return
        try:
            self.project.config_path = self.project.config_path or str(self.current_project_path.parent / DEFAULT_CONFIG_JSON)
            with self.current_project_path.open("w", encoding="utf-8") as handle:
                if self.current_project_path.suffix.lower() in {".json"}:
                    json.dump(self.project_to_dict(), handle, indent=2, ensure_ascii=False)
                else:
                    yaml.safe_dump(self.project_to_dict(), handle, sort_keys=False, allow_unicode=True)
            self.settings.setValue("session/current_project_path", str(self.current_project_path))
            self._store_plot_style_state()
            self.statusBar().showMessage(f"Projekt gespeichert: {self.current_project_path}", 3000)
        except Exception as exc:
            show_critical(self, "Projekt speichern", str(exc))

    def save_project_as(self) -> None:
        start_dir = self.current_project_path.parent if self.current_project_path else Path.cwd()
        start = str(start_dir / DEFAULT_PROJECT_YAML if Path(start_dir).is_dir() else start_dir)
        path, _ = get_save_file_name(self, "Projekt speichern", start, "YAML (*.yaml *.yml);;JSON (*.json)")
        if not path:
            return
        p = Path(path)
        if p.suffix.lower() not in {".yaml", ".yml", ".json"}:
            p = p.with_suffix(".yaml")
        self.current_project_path = p
        self.save_project()

    def load_config_json(self) -> None:
        start = str(Path(self.project.config_path).parent if self.project.config_path else Path.cwd())
        path, _ = get_open_file_name(self, "Config laden", start, "YAML/JSON (*.yaml *.yml *.json)")
        if path:
            self.load_config_from_path(Path(path))

    def load_config_from_path(self, path: Path, silent: bool = False) -> None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                self.config_data = json.load(handle)
            self.project.config_path = str(path)
            self.settings.setValue("session/config_path", str(path))
            detected = self.detected_cylinders()
            if detected and self.project.selected_cylinder not in detected:
                self.project.selected_cylinder = self.config_data.get("active_user_cylinder") or detected[0]
            self.refresh_cylinder_combo()
            preferred_csv = None
            candidate_csv = None
            post = dict(self.config_data.get('postprocessing') or {}) if isinstance(self.config_data, dict) else {}
            csv_path = post.get('csv_path')
            if csv_path:
                candidate_csv = PathManager.resolve_output_file(
                    path,
                    configured_outdir=post.get('outdir'),
                    configured_path=str(csv_path),
                    fallback_name='out.csv',
                )
                preferred_csv, _ = _plot_resolve_preferred_preview_csv(candidate_csv)
            self.update_diagnosis()
            self.populate_signal_tree()
            if preferred_csv is not None and preferred_csv.exists():
                current_preview = Path(self.project.preview_csv_path).resolve() if self.project.preview_csv_path else None
                if current_preview is None or current_preview == candidate_csv or current_preview == preferred_csv:
                    self.load_preview_csv_from_path(preferred_csv, silent=True)
            self.set_dirty()
            if not silent:
                if preferred_csv is not None and preferred_csv.exists():
                    self.statusBar().showMessage(f"Config geladen: {path.name} | Preview bevorzugt: {preferred_csv.name}", 3500)
                else:
                    self.statusBar().showMessage(f"Config geladen: {path}", 2500)
        except Exception as exc:
            show_critical(self, "Config laden", str(exc))

    def load_signals_json(self) -> None:
        start = str(Path(self.project.signals_path).parent if self.project.signals_path else Path.cwd())
        default_candidate = Path(start) / DEFAULT_SIGNALS_JSON
        path, _ = get_open_file_name(self, "Signalkatalog laden", str(default_candidate), "Signal-Katalog (*.yaml *.yml *.json)")
        if path:
            self.load_signals_from_path(Path(path))

    def load_signals_from_path(self, path: Path, silent: bool = False) -> None:
        try:
            self._validate_signal_catalog_path(path)
        except Exception as exc:
            self.catalog.error = str(exc)
            self.populate_signal_tree()
            self.update_diagnosis()
            if not silent:
                show_warning(self, "Signals laden", str(exc))
            return
        self.catalog.load(str(path))
        self.project.signals_path = str(path)
        self.signals_path_label.setText(str(path))
        self.settings.setValue("session/signals_path", str(path))
        self.populate_signal_tree()
        self.update_diagnosis()
        self.set_dirty()
        if not silent:
            self.statusBar().showMessage(f"Signals geladen: {path}", 2500)

    def load_preview_csv(self) -> None:
        start = str(Path(self.project.preview_csv_path).parent if self.project.preview_csv_path else Path.cwd())
        path, _ = get_open_file_name(self, "Preview CSV laden", start, "CSV/Text (*.csv *.txt *.dat);;All files (*.*)")
        if path:
            self.load_preview_csv_from_path(Path(path))

    def load_preview_csv_from_path(self, path: Path, silent: bool = False) -> None:
        self.preview_csv.load(str(path))
        self.project.preview_csv_path = str(path)
        self.csv_path_label.setText(str(path))
        self.settings.setValue("session/preview_csv_path", str(path))
        detected_from_preview = self.detected_cylinders_from_preview()
        if detected_from_preview and self.project.selected_cylinder not in detected_from_preview:
            self.project.selected_cylinder = detected_from_preview[0]
        self.refresh_cylinder_combo()
        self.populate_signal_tree()
        self.update_diagnosis()
        self.set_dirty()
        if not silent:
            self.statusBar().showMessage(f"CSV geladen: {path}", 2500)

    # ---------- templates ----------
    def save_subplot_template(self) -> None:
        sp = self.current_subplot()
        if sp is None:
            return
        path, _ = get_save_file_name(self, "Subplot-Template speichern", str(Path.cwd()), "YAML (*.yaml *.yml);;JSON (*.json)")
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() not in {".yaml", ".yml", ".json"}:
            target = target.with_suffix(".yaml")
        with target.open("w", encoding="utf-8") as handle:
            if target.suffix.lower() == ".json":
                json.dump(asdict(sp), handle, indent=2, ensure_ascii=False)
            else:
                yaml.safe_dump(asdict(sp), handle, sort_keys=False, allow_unicode=True)
        self.statusBar().showMessage("Subplot-Template gespeichert", 2000)

    def load_subplot_template(self) -> None:
        path, _ = get_open_file_name(self, "Subplot-Template laden", str(Path.cwd()), "YAML/JSON (*.yaml *.yml *.json)")
        if not path:
            return
        try:
            src_path = Path(path)
            with src_path.open("r", encoding="utf-8") as handle:
                if src_path.suffix.lower() in {".yaml", ".yml"}:
                    data = yaml.safe_load(handle)
                else:
                    data = json.load(handle)
            sp = SubplotModel(
                id=new_id(),
                title=data.get("title", "Subplot"),
                plot_type=data.get("plot_type", "line"),
                x_signal=data.get("x_signal", "theta_deg"),
                x_title=data.get("x_title", "Theta"),
                x_unit_preset=data.get("x_unit_preset", "deg"),
                x_scale_factor=float(data.get("x_scale_factor", 1.0) or 1.0),
                x_offset=float(data.get("x_offset", 0.0) or 0.0),
                x_limit_mode=data.get("x_limit_mode", "data"),
                x_min=float(data.get("x_min", 0.0) or 0.0),
                x_max=float(data.get("x_max", 720.0) or 720.0),
                y_axes=[axis_model_from_data(axis) for axis in data.get("y_axes", [])] or [AxisModel(title="Y")],
                series=[series_model_from_data(series) for series in data.get("series", [])],
                y_lines=[horizontal_line_model_from_data(y_line) for y_line in data.get("y_lines", [])],
                events=[EventModel(**({**event, "alpha": float(event.get("alpha", 0.9) or 0.9)})) for event in data.get("events", [])],
                legend_visible=bool(data.get("legend_visible", True)),
                legend_position=data.get("legend_position", "best"),
                show_grid=bool(data.get("show_grid", True)),
            )
            fig = self.current_figure()
            if fig is None:
                self.project.figures = [FigureModel(subplots=[sp])]
            else:
                fig.subplots.append(sp)
            self.refresh_all()
            self.subplot_list.setCurrentRow(len(self.current_figure().subplots) - 1)
            self.statusBar().showMessage("Subplot-Template geladen", 2000)
        except Exception as exc:
            show_critical(self, "Template laden", str(exc))

    def save_figure_template(self) -> None:
        fig = self.current_figure()
        if fig is None:
            return
        path, _ = get_save_file_name(self, "Figure-Template speichern", str(Path.cwd()), "YAML (*.yaml *.yml);;JSON (*.json)")
        if not path:
            return
        target = Path(path)
        if target.suffix.lower() not in {".yaml", ".yml", ".json"}:
            target = target.with_suffix(".yaml")
        with target.open("w", encoding="utf-8") as handle:
            if target.suffix.lower() == ".json":
                json.dump(asdict(fig), handle, indent=2, ensure_ascii=False)
            else:
                yaml.safe_dump(asdict(fig), handle, sort_keys=False, allow_unicode=True)
        self.statusBar().showMessage("Figure-Template gespeichert", 2000)

    def load_figure_template(self) -> None:
        path, _ = get_open_file_name(self, "Figure-Template laden", str(Path.cwd()), "YAML/JSON (*.yaml *.yml *.json)")
        if not path:
            return
        try:
            with Path(path).open("r", encoding="utf-8") as handle:
                if Path(path).suffix.lower() in {".yaml", ".yml"}:
                    data = yaml.safe_load(handle) or {}
                else:
                    data = json.load(handle)
            fig = FigureModel(
                id=new_id(),
                title=data.get("title", "Figure"),
                rows=int(data.get("rows", 1)),
                cols=int(data.get("cols", 1)),
                subplots=[],
            )
            for sp_data in data.get("subplots", []):
                fig.subplots.append(SubplotModel(
                    id=new_id(),
                    title=sp_data.get("title", "Subplot"),
                    show_title=bool(sp_data.get("show_title", True)),
                    plot_type=sp_data.get("plot_type", "line"),
                    x_signal=sp_data.get("x_signal", "theta_deg"),
                    x_title=sp_data.get("x_title", "Theta [deg]"),
                    y_axes=[axis_model_from_data(axis) for axis in sp_data.get("y_axes", [])] or [AxisModel(title="Y")],
                    series=[series_model_from_data(series) for series in sp_data.get("series", [])],
                    events=[event_model_from_data(event) for event in sp_data.get("events", [])],
                    y_lines=[horizontal_line_model_from_data(y_line) for y_line in sp_data.get("y_lines", [])],
                    legend_visible=bool(sp_data.get("legend_visible", True)),
                    legend_position=sp_data.get("legend_position", "best"),
                    show_grid=bool(sp_data.get("show_grid", True)),
                ))
            if not fig.subplots:
                fig.subplots = [SubplotModel()]
            self.project.figures.append(fig)
            self.refresh_all()
            self.figure_list.setCurrentRow(len(self.project.figures) - 1)
            self.statusBar().showMessage("Figure-Template geladen", 2000)
        except Exception as exc:
            show_critical(self, "Template laden", str(exc))

    def save_layout_template(self) -> None:
        path, _ = get_save_file_name(self, "Layout-Template speichern", str(Path.cwd()), "YAML (*.yaml *.yml);;JSON (*.json)")
        if not path:
            return
        payload = {"name": self.project.name, "figures": [asdict(fig) for fig in self.project.figures]}
        target = Path(path)
        if target.suffix.lower() not in {".yaml", ".yml", ".json"}:
            target = target.with_suffix(".yaml")
        with target.open("w", encoding="utf-8") as handle:
            if target.suffix.lower() == ".json":
                json.dump(payload, handle, indent=2, ensure_ascii=False)
            else:
                yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)
        self.statusBar().showMessage("Layout-Template gespeichert", 2000)

    def load_layout_template(self) -> None:
        path, _ = get_open_file_name(self, "Layout-Template laden", str(Path.cwd()), "JSON/YAML (*.json *.yaml *.yml)")
        if not path:
            return
        try:
            with Path(path).open("r", encoding="utf-8") as handle:
                if Path(path).suffix.lower() in {".yaml", ".yml"}:
                    data = yaml.safe_load(handle) or {}
                else:
                    data = json.load(handle)
            figures: list[FigureModel] = []
            for fig_data in data.get("figures", []):
                fig = FigureModel(id=new_id(), title=fig_data.get("title", "Figure"), rows=int(fig_data.get("rows", 1)), cols=int(fig_data.get("cols", 1)), subplots=[])
                for sp_data in fig_data.get("subplots", []):
                    fig.subplots.append(SubplotModel(
                        id=new_id(),
                        title=sp_data.get("title", "Subplot"),
                        plot_type=sp_data.get("plot_type", "line"),
                        x_signal=sp_data.get("x_signal", "theta_deg"),
                        x_title=sp_data.get("x_title", "Theta"),
                        x_unit_preset=sp_data.get("x_unit_preset", "deg"),
                        x_scale_factor=float(sp_data.get("x_scale_factor", 1.0) or 1.0),
                        x_offset=float(sp_data.get("x_offset", 0.0) or 0.0),
                        x_limit_mode=sp_data.get("x_limit_mode", "data"),
                        x_min=float(sp_data.get("x_min", 0.0) or 0.0),
                        x_max=float(sp_data.get("x_max", 720.0) or 720.0),
                        y_axes=[axis_model_from_data(axis) for axis in sp_data.get("y_axes", [])] or [AxisModel(title="Y")],
                        series=[series_model_from_data(series) for series in sp_data.get("series", [])],
                        events=[event_model_from_data(event) for event in sp_data.get("events", [])],
                        y_lines=[horizontal_line_model_from_data(y_line) for y_line in sp_data.get("y_lines", [])],
                        legend_visible=bool(sp_data.get("legend_visible", True)),
                        legend_position=sp_data.get("legend_position", "best"),
                        show_grid=bool(sp_data.get("show_grid", True)),
                    ))
                if not fig.subplots:
                    fig.subplots = [SubplotModel()]
                figures.append(fig)
            if figures:
                self.project.figures = figures
                self.refresh_all()
                self.statusBar().showMessage("Layout-Template geladen", 2000)
        except Exception as exc:
            show_critical(self, "Layout laden", str(exc))

    def save_style_template(self) -> None:
        path, _ = get_save_file_name(self, "Plot-Style speichern", str(Path.cwd()), "YAML (*.yaml *.yml);;JSON (*.json)")
        if not path:
            return
        try:
            payload = {
                "template_type": "plot_style",
                "style": asdict(self.project.style),
            }
            target = Path(path)
            if target.suffix.lower() not in {".yaml", ".yml", ".json"}:
                target = target.with_suffix(".yaml")
            with target.open("w", encoding="utf-8") as handle:
                if target.suffix.lower() == ".json":
                    json.dump(payload, handle, indent=2, ensure_ascii=False)
                else:
                    yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=True)
            self.settings.setValue("plot_style/last_template_path", str(target))
            self._store_plot_style_state()
            self.statusBar().showMessage(f"Plot-Style gespeichert: {target}", 2500)
        except Exception as exc:
            show_critical(self, "Plot-Style speichern", str(exc))

    def load_style_template(self) -> None:
        start_dir = str(self.settings.value("plot_style/last_template_path", str(Path.cwd())) or str(Path.cwd()))
        path, _ = get_open_file_name(self, "Plot-Style laden", start_dir, "YAML/JSON (*.yaml *.yml *.json)")
        if not path:
            return
        try:
            with Path(path).open("r", encoding="utf-8") as handle:
                if Path(path).suffix.lower() in {".yaml", ".yml"}:
                    data = yaml.safe_load(handle) or {}
                else:
                    data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("Ungültiges Plot-Style-Template: JSON-Objekt erwartet.")
            style_data = data.get("style", data)
            if not isinstance(style_data, dict):
                raise ValueError("Ungültiges Plot-Style-Template: 'style'-Objekt fehlt.")

            base = asdict(StyleModel.preset("Light Engineering"))
            base.update(style_data)
            self.project.style = style_model_from_data(base)
            self.settings.setValue("plot_style/last_template_path", str(Path(path)))
            self._store_plot_style_state()
            self.refresh_all()
            self.set_dirty()
            self.statusBar().showMessage(f"Plot-Style geladen: {path}", 2500)
        except Exception as exc:
            show_critical(self, "Plot-Style laden", str(exc))

    # ---------- tree population ----------
    def _signal_filter_tokens(self) -> list[str]:
        raw = self.signals_filter_edit.text().strip().lower()
        return [token for token in raw.split() if token]

    def _signal_matches_filter(self, signal: str, resolved: str, tokens: list[str]) -> bool:
        if not tokens:
            return True
        haystacks = [signal.lower(), resolved.lower()]
        return all(any(token in hay for hay in haystacks) for token in tokens)

    def _apply_filter_match_highlight(self, item: QTreeWidgetItem, *, is_direct_hit: bool, token_text: str) -> None:
        if not is_direct_hit:
            item.setData(0, Qt.UserRole + 1, False)
            return
        highlight_brush = QBrush(QColor("#fff3b0"))
        item.setBackground(0, highlight_brush)
        item.setBackground(1, highlight_brush)
        font = item.font(0)
        font.setBold(True)
        item.setFont(0, font)
        item.setFont(1, font)
        item.setData(0, Qt.UserRole + 1, True)
        item.setToolTip(1, f"Filter-Treffer: {token_text}")

    def populate_signal_tree(self) -> None:
        self.signal_tree.clear()
        self.signals_path_label.setText(self.project.signals_path)
        self.csv_path_label.setText(self.project.preview_csv_path)
        filter_tokens = self._signal_filter_tokens()
        filter_text = " ".join(filter_tokens)
        only_available = self.action_show_available_only.isChecked()
        if hasattr(self, "available_only_check") and self.available_only_check.isChecked() != only_available:
            self.available_only_check.blockSignals(True)
            self.available_only_check.setChecked(only_available)
            self.available_only_check.blockSignals(False)
        if self.catalog.error:
            item = QTreeWidgetItem([f"Fehler: {self.catalog.error}", ""])
            self.signal_tree.addTopLevelItem(item)
            return
        tree_data = self.catalog.items_for_tree()
        cylinder = self.project.selected_cylinder or "user_cylinder_1"
        headers = self.preview_csv.available_set
        first_hit_item: QTreeWidgetItem | None = None
        total_hits = 0
        for top_name, categories in tree_data.items():
            top_item = QTreeWidgetItem([top_name, ""])
            added = False
            top_match_count = 0
            for category_name, signals in categories.items():
                cat_item = QTreeWidgetItem([category_name, ""])
                cat_added = False
                cat_match_count = 0
                for signal in signals:
                    resolved = self.catalog.resolve(signal, cylinder)
                    direct_hit = self._signal_matches_filter(signal, resolved, filter_tokens)
                    if filter_tokens and not direct_hit:
                        continue
                    status = ""
                    color = None
                    found = None
                    mode = ""
                    if headers:
                        found, mode = self.catalog.find_available_signal(signal, headers, cylinder)
                        status = found if found else "missing"
                        color = QColor("#17803d") if found else QColor("#b42318")
                    elif only_available:
                        continue
                    if only_available and not found:
                        continue
                    item = QTreeWidgetItem([signal, status])
                    item.setData(0, Qt.UserRole, signal)
                    tip = f"Resolved: {resolved}"
                    if found:
                        tip += f"\nMatched: {found} ({mode})"
                    if direct_hit and filter_tokens:
                        tip += f"\nFilter-Treffer: {filter_text}"
                    item.setToolTip(0, tip)
                    if color is not None:
                        item.setForeground(0, color)
                        item.setForeground(1, color)
                    if direct_hit and filter_tokens:
                        cat_match_count += 1
                        total_hits += 1
                        if first_hit_item is None:
                            first_hit_item = item
                    self._apply_filter_match_highlight(item, is_direct_hit=bool(direct_hit and filter_tokens), token_text=filter_text)
                    cat_item.addChild(item)
                    cat_added = True
                if cat_added:
                    if filter_tokens and cat_match_count > 0:
                        cat_item.setText(1, f"{cat_match_count} Treffer")
                        cat_item.setExpanded(True)
                    top_item.addChild(cat_item)
                    added = True
                    top_match_count += cat_match_count
            if added:
                if filter_tokens and top_match_count > 0:
                    top_item.setText(1, f"{top_match_count} Treffer")
                self.signal_tree.addTopLevelItem(top_item)
                top_item.setExpanded(True)
        if first_hit_item is not None:
            self.signal_tree.setCurrentItem(first_hit_item)
            self.signal_tree.scrollToItem(first_hit_item)
            self.statusBar().showMessage(f"Signalfilter: {total_hits} Treffer", 2500)
        elif filter_tokens:
            self.statusBar().showMessage("Signalfilter: keine Treffer", 2500)
        self.signal_tree.resizeColumnToContents(0)
        self.signal_tree.resizeColumnToContents(1)

    def on_signal_tree_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        signal = item.data(0, Qt.UserRole)
        if signal:
            self.add_series_from_signal(str(signal))

    # ---------- project modifications ----------
    def add_figure(self) -> None:
        fig = FigureModel(title=f"Figure {len(self.project.figures) + 1}")
        axis_id = fig.subplots[0].y_axes[0].id
        fig.subplots[0].series = [SeriesModel(signal_key="p_cyl_pa", label="p_cyl_pa", axis_id=axis_id, color="#1f77b4")]
        self.project.figures.append(fig)
        self.refresh_all()
        self.figure_list.setCurrentRow(len(self.project.figures) - 1)
        self.set_dirty("Figure hinzugefügt")

    def copy_figure(self) -> None:
        fig = self.current_figure()
        if fig is None:
            return
        clone = copy.deepcopy(fig)
        clone.id = new_id()
        clone.title = f"{fig.title} Copy"
        for sp in clone.subplots:
            sp.id = new_id()
            for ax in sp.y_axes:
                old = ax.id
                ax.id = new_id()
                for ser in sp.series:
                    if ser.axis_id == old:
                        ser.axis_id = ax.id
            for ser in sp.series:
                ser.id = new_id()
        self.project.figures.append(clone)
        self.refresh_all()
        self.figure_list.setCurrentRow(len(self.project.figures) - 1)
        self.set_dirty("Figure kopiert")

    def delete_figure(self) -> None:
        if len(self.project.figures) <= 1:
            return
        idx = self.figure_list.currentRow()
        if idx < 0:
            return
        del self.project.figures[idx]
        self.refresh_all()
        self.figure_list.setCurrentRow(max(0, idx - 1))
        self.set_dirty("Figure gelöscht")

    def add_subplot(self) -> None:
        fig = self.current_figure()
        if fig is None:
            return
        sp = SubplotModel(title=f"Subplot {len(fig.subplots) + 1}")
        axis_id = sp.y_axes[0].id
        sp.series = [SeriesModel(signal_key="p_cyl_pa", label="p_cyl_pa", axis_id=axis_id, color="#1f77b4")]
        fig.subplots.append(sp)
        self.refresh_all()
        self.subplot_list.setCurrentRow(len(fig.subplots) - 1)
        self.set_dirty("Subplot hinzugefügt")

    def copy_subplot(self) -> None:
        fig = self.current_figure()
        sp = self.current_subplot()
        if fig is None or sp is None:
            return
        clone = self._clone_subplot_model(sp)
        fig.subplots.append(clone)
        self.refresh_all()
        self._select_subplot_in_figure(self.figure_list.currentRow(), clone.id)
        self.set_dirty("Subplot kopiert")

    def delete_subplot(self) -> None:
        fig = self.current_figure()
        if fig is None or len(fig.subplots) <= 1:
            return
        idx = self.subplot_list.currentRow()
        if idx < 0:
            return
        del fig.subplots[idx]
        self.refresh_all()
        self.subplot_list.setCurrentRow(max(0, idx - 1))
        self.set_dirty("Subplot gelöscht")

    def move_subplot(self, delta: int) -> None:
        fig = self.current_figure()
        idx = self.subplot_list.currentRow()
        if fig is None or idx < 0:
            return
        new_idx = idx + delta
        if not (0 <= new_idx < len(fig.subplots)):
            return
        fig.subplots[idx], fig.subplots[new_idx] = fig.subplots[new_idx], fig.subplots[idx]
        self.refresh_all()
        self.subplot_list.setCurrentRow(new_idx)
        self.set_dirty("Subplot verschoben")

    def add_axis(self) -> None:
        sp = self.current_subplot()
        if sp is None:
            return
        side = "right" if any(ax.side == "left" for ax in sp.y_axes) else "left"
        offset = 0.0
        if side == "right":
            right_offsets = [ax.spine_offset for ax in sp.y_axes if ax.side == "right"]
            offset = (max(right_offsets) + 0.12) if right_offsets else 0.0
        axis = AxisModel(title=f"Y{len(sp.y_axes) + 1}", side=side, spine_offset=offset, color="#d62728" if side == "right" else "#1f77b4")
        sp.y_axes.append(axis)
        self.refresh_all()
        self.axis_list.setCurrentRow(len(sp.y_axes) - 1)
        self.set_dirty("Y-Achse hinzugefügt")

    def delete_axis(self) -> None:
        sp = self.current_subplot()
        axis = self.current_axis()
        if sp is None or axis is None or len(sp.y_axes) <= 1:
            return
        if any(ser.axis_id == axis.id for ser in sp.series):
            replacement = next((a for a in sp.y_axes if a.id != axis.id), None)
            if replacement is None:
                return
            for ser in sp.series:
                if ser.axis_id == axis.id:
                    ser.axis_id = replacement.id
        sp.y_axes = [a for a in sp.y_axes if a.id != axis.id]
        self.refresh_all()
        self.set_dirty("Y-Achse gelöscht")

    def add_series(self) -> None:
        self.add_series_from_signal("p_cyl_pa")

    def add_series_from_signal(self, signal: str) -> None:
        sp = self.current_subplot()
        if sp is None:
            return
        axis_id = sp.y_axes[0].id if sp.y_axes else ""
        default_color = next_color(len(sp.series))
        ser = SeriesModel(
            signal_key=signal,
            label=signal,
            axis_id=axis_id,
            color=default_color,
            line_width=self.project.style.default_line_width,
            marker_size=self.project.style.default_marker_size,
        )
        sp.series.append(ser)
        self.refresh_all()
        self.series_list.setCurrentRow(len(sp.series) - 1)
        self.set_dirty(f"Serie hinzugefügt: {signal}")

    def delete_series(self) -> None:
        sp = self.current_subplot()
        idx = self.series_list.currentRow()
        if sp is None or idx < 0 or not sp.series:
            return
        del sp.series[idx]
        self.refresh_all()
        if sp.series:
            self.series_list.setCurrentRow(max(0, idx - 1))
        self.set_dirty("Serie gelöscht")

    def move_series(self, delta: int) -> None:
        sp = self.current_subplot()
        idx = self.series_list.currentRow()
        if sp is None or idx < 0:
            return
        new_idx = idx + delta
        if not (0 <= new_idx < len(sp.series)):
            return
        sp.series[idx], sp.series[new_idx] = sp.series[new_idx], sp.series[idx]
        self.refresh_all()
        self.series_list.setCurrentRow(new_idx)
        self.set_dirty("Serie verschoben")

    # ---------- selection handlers ----------
    def on_figure_selection_changed(self, _row: int) -> None:
        self.loading_ui = True
        try:
            self.refresh_lists()
            self.refresh_subplot_tab()
            self.refresh_axes()
            self.refresh_series()
            self.refresh_events()
        finally:
            self.loading_ui = False
        self._update_project_selection_feedback()
        self.render_preview()

    def add_event(self) -> None:
        sp = self.current_subplot()
        if sp is None:
            return
        sp.events.append(EventModel(label=f"Event {len(sp.events) + 1}", x=0.0, source="manual", source_note="Manuell im Plot-Editor angelegt"))
        self.refresh_events()
        self.event_list.setCurrentRow(len(sp.events) - 1)
        self.set_dirty("Event hinzugefügt")

    def delete_event(self) -> None:
        sp = self.current_subplot()
        idx = self.event_list.currentRow()
        if sp is None or idx < 0 or idx >= len(sp.events):
            return
        sp.events.pop(idx)
        self.refresh_events()
        if sp.events:
            self.event_list.setCurrentRow(max(0, idx - 1))
        self.set_dirty("Event gelöscht")

    def move_event(self, direction: int) -> None:
        sp = self.current_subplot()
        idx = self.event_list.currentRow()
        if sp is None or idx < 0 or idx >= len(sp.events):
            return
        new_idx = max(0, min(len(sp.events) - 1, idx + direction))
        if new_idx == idx:
            return
        sp.events[idx], sp.events[new_idx] = sp.events[new_idx], sp.events[idx]
        self.refresh_events()
        self.event_list.setCurrentRow(new_idx)
        self.set_dirty("Event-Reihenfolge geändert")

    def delete_auto_events_current_subplot(self) -> None:
        sp = self.current_subplot()
        if sp is None:
            return
        before = len(getattr(sp, "events", []) or [])
        sp.events = [event for event in getattr(sp, "events", []) if not self._event_is_auto(event)]
        removed = before - len(sp.events)
        self.refresh_events()
        if removed > 0:
            self.set_dirty(f"{removed} Auto-Events gelöscht")
        else:
            self.statusBar().showMessage("Keine Auto-Events vorhanden", 2500)

    def toggle_lock_auto_events_current_subplot(self) -> None:
        sp = self.current_subplot()
        if sp is None:
            return
        auto_events = [event for event in getattr(sp, "events", []) if self._event_is_auto(event)]
        if not auto_events:
            self.statusBar().showMessage("Keine Auto-Events vorhanden", 2500)
            return
        target_locked = not all(self._event_is_locked(event) for event in auto_events)
        for event in auto_events:
            event.locked = target_locked
            note = str(getattr(event, "source_note", "") or "").strip()
            suffix = "Auto-Event gesperrt" if target_locked else "Auto-Event entsperrt"
            if suffix not in note:
                event.source_note = (note + (" | " if note else "") + suffix).strip()
        self.refresh_events()
        self.set_dirty("Auto-Events gesperrt" if target_locked else "Auto-Events entsperrt")

    def toggle_hide_auto_events_current_subplot(self) -> None:
        sp = self.current_subplot()
        if sp is None:
            return
        auto_events = [event for event in getattr(sp, "events", []) if self._event_is_auto(event)]
        if not auto_events:
            self.statusBar().showMessage("Keine Auto-Events vorhanden", 2500)
            return
        target_visible = all(not bool(getattr(event, "visible", True)) for event in auto_events)
        for event in auto_events:
            event.visible = target_visible
            note = str(getattr(event, "source_note", "") or "").strip()
            suffix = "Auto-Event eingeblendet" if target_visible else "Auto-Event ausgeblendet"
            if suffix not in note:
                event.source_note = (note + (" | " if note else "") + suffix).strip()
        self.refresh_events()
        self.refresh_json_preview()
        self.render_preview()
        self.update_statusbar()
        self.set_dirty("Auto-Events eingeblendet" if target_visible else "Auto-Events ausgeblendet")

    def delete_auto_events_by_selected_type_current_subplot(self) -> None:
        sp = self.current_subplot()
        if sp is None:
            return
        before = list(getattr(sp, "events", []) or [])
        scoped = self._auto_events_matching_scope(before)
        if not scoped:
            self.statusBar().showMessage("Keine passenden Auto-Events für den gewählten Typ vorhanden", 2500)
            return
        scoped_ids = {event.id for event in scoped}
        sp.events = [event for event in before if event.id not in scoped_ids]
        self.refresh_events()
        self.refresh_json_preview()
        self.render_preview()
        self.update_statusbar()
        self.set_dirty("Auto-Events des gewählten Typs gelöscht")

    def toggle_hide_auto_events_by_selected_type_current_subplot(self) -> None:
        sp = self.current_subplot()
        if sp is None:
            return
        scoped = self._auto_events_matching_scope(list(getattr(sp, "events", []) or []))
        if not scoped:
            self.statusBar().showMessage("Keine passenden Auto-Events für den gewählten Typ vorhanden", 2500)
            return
        target_visible = all(not bool(getattr(event, "visible", True)) for event in scoped)
        for event in scoped:
            event.visible = target_visible
        self.refresh_events()
        self.refresh_json_preview()
        self.render_preview()
        self.update_statusbar()
        self.set_dirty("Auto-Events des gewählten Typs eingeblendet" if target_visible else "Auto-Events des gewählten Typs ausgeblendet")

    def toggle_lock_auto_events_by_selected_type_current_subplot(self) -> None:
        sp = self.current_subplot()
        if sp is None:
            return
        scoped = self._auto_events_matching_scope(list(getattr(sp, "events", []) or []))
        if not scoped:
            self.statusBar().showMessage("Keine passenden Auto-Events für den gewählten Typ vorhanden", 2500)
            return
        target_locked = not all(self._event_is_locked(event) for event in scoped)
        for event in scoped:
            event.locked = target_locked
        self.refresh_events()
        self.refresh_json_preview()
        self.render_preview()
        self.update_statusbar()
        self.set_dirty("Auto-Events des gewählten Typs gesperrt" if target_locked else "Auto-Events des gewählten Typs entsperrt")

    def convert_current_manual_event_to_auto(self) -> None:
        event = self.current_event()
        if event is None:
            return
        if self._event_is_auto(event):
            self.statusBar().showMessage("Aktuelles Event ist bereits ein Auto-Event", 2500)
            return
        event.source = "config_auto"
        event.locked = False
        event.source_note = "Manuelles Event vom Benutzer in Auto-Event zurückgewandelt"
        self.refresh_events()
        self.set_dirty("Manuelles Event in Auto-Event zurückgewandelt")

    def on_event_meta_changed(self, *_args) -> None:
        if self.loading_ui:
            return
        event = self.current_event()
        if event is None:
            return
        if self._event_is_locked(event):
            self.refresh_event_editor()
            self.statusBar().showMessage("Gesperrte Auto-Events können nicht direkt bearbeitet werden", 3000)
            return
        if str(getattr(event, "source", "manual") or "manual").strip().lower() != "manual":
            event.source = "manual"
            event.locked = False
            if not str(getattr(event, "source_note", "") or "").strip():
                event.source_note = "Vom Benutzer im Plot-Editor angepasst"
        event.label = self.event_label_edit.text().strip()
        event.event_type = self.event_type_combo.currentText() or "custom"
        event.x = float(self.event_x_spin.value())
        event.visible = self.event_visible_check.isChecked()
        event.show_label = self.event_show_label_check.isChecked()
        event.color = self.event_color_button.color()
        event.line_style = self.event_line_style_combo.currentText() or ":"
        event.line_width = float(self.event_line_width_spin.value())
        event.alpha = float(self.event_alpha_spin.value())
        event.label_rotation = float(self.event_label_rotation_spin.value())
        event.label_font_size = float(self.event_label_font_size_spin.value())
        event.label_bg_color = self.event_label_bg_color_button.color()
        event.label_bg_alpha = float(self.event_label_bg_alpha_spin.value())
        event.label_border_color = self.event_label_border_color_button.color()
        event.label_y = float(self.event_label_y_spin.value())
        event.label_ha = self.event_label_ha_combo.currentText() or "right"
        event.label_va = self.event_label_va_combo.currentText() or "top"
        self.refresh_events()
        self.refresh_json_preview()
        self.render_preview()
        self.update_statusbar()
        self.set_dirty()

    def on_subplot_selection_changed(self, _row: int) -> None:
        self.loading_ui = True
        try:
            self.refresh_subplot_tab()
            self.refresh_axes()
            self.refresh_series()
            self.refresh_events()
        finally:
            self.loading_ui = False
        self._update_project_selection_feedback()
        self.render_preview()

    def on_axis_selection_changed(self, _row: int) -> None:
        self.refresh_axis_editor()

    def on_series_selection_changed(self, _row: int) -> None:
        self.refresh_series_editor()

    def on_event_selection_changed(self, _row: int) -> None:
        self.refresh_event_editor()

    # ---------- style editor ----------
    def open_style_editor(self) -> None:
        dlg = StyleDialog(self, self.project.style)
        if exec_dialog(dlg) == int(QDialog.Accepted):
            self.project.style = dlg.result_style()
            self._store_plot_style_state()
            self.set_dirty("Plot-Stil aktualisiert")

    # ---------- auto timing plots ----------
    def create_auto_timing_plot(self, plot_type: str) -> None:
        fig = self.current_figure()
        if fig is None:
            return
        sp = SubplotModel(
            title="Timing" if plot_type == "timing_cartesian" else "Timing Polar",
            plot_type=plot_type,
            x_signal="theta_deg",
            x_title="Theta",
            x_unit_preset="deg",
            x_scale_factor=1.0,
            x_offset=0.0,
            x_limit_mode="data",
            x_min=0.0,
            x_max=720.0,
            y_axes=[AxisModel(title="Opening", side="left", color="#1f77b4")],
            series=[],
            legend_visible=True,
            legend_position="best",
            show_grid=True,
        )
        fig.subplots.append(sp)
        self.refresh_all()
        self.subplot_list.setCurrentRow(len(fig.subplots) - 1)
        self.set_dirty("Auto-Timing-Plot erstellt")

    # ---------- YAML preview ----------
    def refresh_json_preview(self) -> None:
        try:
            self.json_preview.setPlainText(yaml.safe_dump(self.project_to_dict(), sort_keys=False, allow_unicode=True))
        except Exception as exc:
            self.json_preview.setPlainText(str(exc))

    # ---------- data resolution ----------
    def build_column_cache(self) -> dict[str, list[Any]]:
        cache: dict[str, list[Any]] = {}
        for header in self.preview_csv.headers:
            cache[header] = [row.get(header) for row in self.preview_csv.rows]
        return cache

    def resolve_series_values(self, signal_key: str) -> tuple[list[float] | None, str]:
        if not self.preview_csv.rows:
            return None, "No preview CSV loaded"
        cache = self.build_column_cache()
        found, mode = self.catalog.find_available_signal(signal_key, set(cache.keys()), self.project.selected_cylinder)
        if found:
            values = [coerce_float(v) for v in cache.get(found, [])]
            return values, f"{mode}: {found}"
        derived = self.catalog.derived_data(signal_key, cache)
        if derived is not None:
            return [coerce_float(v) for v in derived], "derived alias"
        return None, "missing"

    def resolve_x_values(self, signal_key: str, length_hint: int = 0) -> tuple[list[float] | None, str]:
        values, how = self.resolve_series_values(signal_key)
        if values is not None:
            return values, how
        if signal_key in {"index", "sample"} or not signal_key:
            n = length_hint or len(self.preview_csv.rows)
            return [float(i) for i in range(n)], "generated"
        if signal_key in {"theta_deg", "theta_local_deg", "theta_deg_cycle"} and not self.preview_csv.rows:
            return None, "missing"
        return None, how

    # ---------- rendering ----------
    def apply_style_to_axes(self, ax, subplot: SubplotModel) -> None:
        style = self.project.style
        ax.set_facecolor(style.axes_facecolor)
        for spine in ax.spines.values():
            spine.set_color(style.text_color)
        ax.tick_params(colors=style.text_color, labelsize=style.tick_label_size)
        ax.xaxis.label.set_color(style.text_color)
        ax.xaxis.label.set_size(style.axis_label_size)
        ax.yaxis.label.set_color(style.text_color)
        ax.yaxis.label.set_size(style.axis_label_size)
        ax.title.set_color(style.text_color)
        if style.grid_visible and subplot.show_grid:
            ax.grid(True, color=style.grid_color, alpha=style.grid_alpha)
        else:
            ax.grid(False)
        if self._is_theta_subplot(subplot):
            if getattr(subplot, 'x_limit_mode', 'data') == 'manual':
                x_min, x_max = self._theta_xlim_for_subplot(subplot)
                ax.set_xlim(x_min, x_max)
            ax.xaxis.set_major_locator(MultipleLocator(180.0))
            ax.xaxis.set_minor_locator(MultipleLocator(60.0))
            if style.grid_visible and subplot.show_grid:
                ax.grid(True, which='major', color=style.grid_color, alpha=max(style.grid_alpha, 0.35))
                ax.grid(True, which='minor', color=style.grid_color, alpha=min(style.grid_alpha, 0.22))

    def render_preview(self) -> None:
        self.preview_widget.figure.clear()
        self.preview_widget.clear_interaction_targets()
        figure = self.current_figure()
        if figure is None:
            self.preview_widget.refresh()
            return
        mpl_fig = self.preview_widget.figure
        style = self.project.style
        mpl_fig.set_facecolor(style.background_color)
        if style.figure_title_visible and str(figure.title or "").strip():
            try:
                mpl_fig.suptitle(figure.title, color=style.text_color, fontsize=style.figure_title_size, fontfamily=style.font_family)
            except Exception:
                mpl_fig.suptitle(figure.title)

        total = max(1, len(figure.subplots))
        eff_cols = max(1, figure.cols)
        eff_rows = max(1, figure.rows)
        if eff_rows * eff_cols < total:
            eff_rows = int(math.ceil(total / eff_cols))
        axes_to_subplot: dict[Any, int] = {}
        artist_targets: list[tuple[Any, int, str]] = []
        for idx, subplot in enumerate(figure.subplots, start=1):
            subplot_index = idx - 1
            is_polar = subplot.plot_type == "timing_polar"
            ax = mpl_fig.add_subplot(eff_rows, eff_cols, idx, projection="polar" if is_polar else None)
            axes_to_subplot[ax] = subplot_index
            self.apply_style_to_axes(ax, subplot)
            if subplot.plot_type in {"timing_cartesian", "timing_polar"}:
                self.render_timing_subplot(ax, subplot)
                self.render_subplot_events(ax, subplot)
                continue
            axis_map = self.build_axis_map(ax, subplot)
            for mapped_ax in axis_map.values():
                axes_to_subplot[mapped_ax] = subplot_index
            self.render_subplot_horizontal_lines(ax, subplot, axis_map)
            artist_targets.extend(self.render_regular_subplot(ax, subplot, axis_map, subplot_index))
            self.render_subplot_events(ax, subplot)
            self.render_subplot_text_box(ax, subplot)
        self.preview_widget.set_interaction_targets(axes_to_subplot, artist_targets)
        if style.tight_layout:
            try:
                pass#mpl_fig.tight_layout(rect=(0, 0, 1, 0.97))
            except Exception:
                pass
        self.preview_widget.refresh()

    def build_axis_map(self, base_ax, subplot: SubplotModel) -> dict[str, Any]:
        axis_map: dict[str, Any] = {}
        left_used = False
        right_count = 0
        for axis in subplot.y_axes:
            if not axis.visible:
                continue
            if axis.side == "left" and not left_used:
                ax = base_ax
                left_used = True
            else:
                ax = base_ax.twinx()
                if axis.side == "right":
                    ax.spines["right"].set_position(("axes", 1.0 + axis.spine_offset))
                else:
                    ax.spines["left"].set_position(("axes", -axis.spine_offset))
                    ax.yaxis.set_label_position("left")
                    ax.yaxis.tick_left()
                right_count += 1
            ax.set_ylabel(axis.title, color=axis.color or self.project.style.text_color, fontsize=self.project.style.axis_label_size)
            ax.tick_params(axis="y", colors=axis.color or self.project.style.text_color, labelsize=self.project.style.tick_label_size)
            ax.spines["right" if axis.side == "right" else "left"].set_color(axis.color or self.project.style.text_color)
            axis_map[axis.id] = ax
        if not axis_map and subplot.y_axes:
            axis_map[subplot.y_axes[0].id] = base_ax
        base_ax.set_xlabel(axis_title_with_unit(subplot.x_title or subplot.x_signal, getattr(subplot, "x_unit_preset", "raw")), color=self.project.style.text_color, fontsize=self.project.style.axis_label_size)
        if getattr(subplot, "show_title", True) and self.project.style.subplot_title_visible and str(subplot.title or "").strip():
            base_ax.set_title(subplot.title, fontsize=self.project.style.title_size, color=self.project.style.text_color)
        else:
            base_ax.set_title("")
        return axis_map

    def _is_theta_subplot(self, subplot: SubplotModel) -> bool:
        x_signal = str(getattr(subplot, 'x_signal', '') or '').lower()
        return x_signal.endswith('theta_deg') or x_signal.endswith('theta_local_deg') or x_signal in {'theta_deg', 'theta_local_deg'}

    def _theta_xlim_for_subplot(self, subplot: SubplotModel) -> tuple[float, float]:
        cycle_type = str(((self.config_data.get('engine') or {}).get('cycle_type') or '4T')).upper()
        cycle_deg = 360.0 if cycle_type == '2T' else 720.0
        if getattr(subplot, 'x_limit_mode', 'data') == 'manual':
            return float(getattr(subplot, 'x_min', 0.0)), float(getattr(subplot, 'x_max', cycle_deg))
        if getattr(subplot, 'x_start_at_zero', True):
            return 0.0, cycle_deg
        return 0.0, cycle_deg

    def _split_theta_segments(self, x_values: list[float], y_values: list[float], cycle_span: float) -> list[tuple[list[float], list[float]]]:
        if not x_values or not y_values:
            return []
        if len(x_values) != len(y_values):
            n = min(len(x_values), len(y_values))
            x_values = list(x_values[:n])
            y_values = list(y_values[:n])
        if len(x_values) <= 1:
            return [(list(x_values), list(y_values))]
        split_threshold = max(1.0, 0.05 * float(cycle_span or 0.0))
        segments: list[tuple[list[float], list[float]]] = []
        start = 0
        for idx in range(1, len(x_values)):
            if float(x_values[idx]) < float(x_values[idx - 1]) - split_threshold:
                segments.append((list(x_values[start:idx]), list(y_values[start:idx])))
                start = idx
        segments.append((list(x_values[start:]), list(y_values[start:])))
        out: list[tuple[list[float], list[float]]] = []
        for xs, ys in segments:
            if xs and ys:
                out.append((xs, ys))
        return out

    def _event_x_value_to_plot(self, subplot: SubplotModel, x_value: float) -> float:
        return float(transform_numeric_value(x_value, getattr(subplot, "x_unit_preset", "raw"), getattr(subplot, "x_scale_factor", 1.0), getattr(subplot, "x_offset", 0.0)) or x_value)

    def render_subplot_events(self, base_ax, subplot: SubplotModel) -> None:
        events = [event for event in getattr(subplot, "events", []) if getattr(event, "visible", True)]
        if not events:
            return
        for idx, event in enumerate(events):
            x_plot = self._event_x_value_to_plot(subplot, float(getattr(event, "x", 0.0) or 0.0))
            color = getattr(event, "color", "#666666") or "#666666"
            line_style = getattr(event, "line_style", ":") or ":"
            line_width = float(getattr(event, "line_width", 1.0) or 1.0)
            alpha = max(0.0, min(1.0, float(getattr(event, "alpha", 0.9) or 0.9)))
            try:
                base_ax.axvline(x=x_plot, color=color, linestyle=line_style, linewidth=line_width, alpha=alpha, zorder=0)
            except Exception:
                continue
            label = str(getattr(event, "label", "") or "").strip()
            if label and getattr(event, "show_label", True):
                y_default = max(0.08, 0.98 - 0.05 * (idx % 5))
                y_pos = float(getattr(event, "label_y", y_default) or y_default)
                rotation = float(getattr(event, "label_rotation", 90.0) or 90.0)
                fontsize = float(getattr(event, "label_font_size", max(7, self.project.style.font_size - 2)) or max(7, self.project.style.font_size - 2))
                facecolor = str(getattr(event, "label_bg_color", self.project.style.axes_facecolor) or self.project.style.axes_facecolor)
                edgecolor = str(getattr(event, "label_border_color", "none") or "none")
                bg_alpha = max(0.0, min(1.0, float(getattr(event, "label_bg_alpha", min(1.0, alpha * 0.85)) or min(1.0, alpha * 0.85))))
                ha = str(getattr(event, "label_ha", "right") or "right")
                va = str(getattr(event, "label_va", "top") or "top")
                base_ax.text(x_plot, y_pos, label, rotation=rotation, transform=base_ax.get_xaxis_transform(), ha=ha, va=va, fontsize=fontsize, color=color,
                                 bbox={"facecolor": facecolor, "edgecolor": edgecolor, "alpha": bg_alpha, "pad": 0.6})

    def _preview_column(self, signal_key: str) -> list[float]:
        if not signal_key or not self.preview_csv.rows:
            return []
        values, _ = self.resolve_series_values(signal_key)
        if values is None:
            return []
        out: list[float] = []
        for value in values:
            numeric = coerce_float(value)
            out.append(float(numeric) if numeric is not None and math.isfinite(float(numeric)) else float("nan"))
        return out

    def _preview_trapz(self, xs: list[float], ys: list[float], *, absolute: bool = False) -> float | None:
        total = 0.0
        used = False
        for idx in range(1, min(len(xs), len(ys))):
            x0, x1 = xs[idx - 1], xs[idx]
            y0, y1 = ys[idx - 1], ys[idx]
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

    def _preview_metric_imep(self, metric: dict[str, Any]) -> float | None:
        cylinder = str(metric.get("cylinder", "") or "").strip()
        p_key = str(metric.get("pressure_signal", "") or (f"{cylinder}_p_Pa" if cylinder else "")).strip()
        v_key = str(metric.get("volume_signal", "") or (f"{cylinder}_V_m3" if cylinder else "")).strip()
        if not p_key or not v_key:
            return None
        p_values = self._preview_column(p_key)
        v_values = self._preview_column(v_key)
        work_j = self._preview_trapz(v_values, p_values)
        finite_v = [value for value in v_values if math.isfinite(value)]
        swept = max(finite_v) - min(finite_v) if finite_v else None
        if work_j is None or swept is None or swept <= 1.0e-18:
            return None
        return work_j / swept / 1.0e5

    def _preview_metric_value(self, metric: dict[str, Any], subplot: SubplotModel) -> float | None:
        if str(metric.get("kind", "") or "").lower().strip() == "imep":
            value = self._preview_metric_imep(metric)
        else:
            key = str(metric.get("signal_key", "") or "").strip()
            values = self._preview_column(key)
            finite_values = [value for value in values if math.isfinite(value)]
            if not finite_values:
                return None
            mode = str(metric.get("mode", "last") or "last").lower().strip()
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
                x_key = str(metric.get("x_signal", "") or getattr(subplot, "x_signal", "t_s") or "t_s")
                value = self._preview_trapz(self._preview_column(x_key), values, absolute=bool(metric.get("absolute", False)))
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

    def _preview_format_metric(self, value: float | None, metric: dict[str, Any]) -> str:
        unit = str(metric.get("unit", "") or "").strip()
        try:
            digits = int(metric.get("digits", 2) or 2)
        except Exception:
            digits = 2
        if value is None or not math.isfinite(value):
            return "n/a"
        if bool(metric.get("scientific", False)):
            return f"{value:.{max(0, digits)}e} {unit}".strip()
        if abs(value) >= 1000.0 or (abs(value) < 0.01 and value != 0.0):
            return f"{value:.{max(1, digits)}g} {unit}".strip()
        return f"{value:.{max(0, digits)}f} {unit}".strip()

    def _readme_table_values(self, path: Path) -> dict[str, tuple[str, str]]:
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

    def _readme_values_for_text_box(self, info: dict[str, Any]) -> dict[str, tuple[str, str]]:
        candidates: list[Path] = []
        configured = str(info.get("readme_path", "") or info.get("path", "") or "").strip()
        if configured:
            raw = Path(configured)
            candidates.append(raw if raw.is_absolute() else Path.cwd() / raw)
            if self.project.preview_csv_path:
                candidates.append(raw if raw.is_absolute() else Path(self.project.preview_csv_path).resolve().parent / raw)
            if self.project.config_path:
                candidates.append(raw if raw.is_absolute() else Path(self.project.config_path).resolve().parent / raw)
        if self.project.preview_csv_path:
            csv_path = Path(self.project.preview_csv_path).resolve()
            candidates.extend([csv_path.parent / "README.md", csv_path.parent.parent / "README.md"])
        if self.project.config_path:
            project_path = Path(self.project.config_path).resolve()
            candidates.extend([project_path.parent / "README.md", project_path.parent.parent / "README.md"])
        candidates.append(Path.cwd() / "README.md")
        seen: set[Path] = set()
        for candidate in candidates:
            try:
                resolved = candidate.resolve()
            except Exception:
                resolved = candidate
            if resolved in seen:
                continue
            seen.add(resolved)
            values = self._readme_table_values(resolved)
            if values:
                return values
        return {}

    def _readme_text_box_lines(self, info: dict[str, Any]) -> list[str]:
        readme_values = self._readme_values_for_text_box(info)
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
        return lines

    def render_subplot_text_box(self, base_ax, subplot: SubplotModel) -> None:
        info = getattr(subplot, "text_box", {}) or {}
        if not isinstance(info, dict) or not bool(info.get("enabled", False)):
            return
        if str(info.get("source", "") or "").lower().strip() == "readme":
            lines = self._readme_text_box_lines(info)
        else:
            lines = []
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
                separator = str(metric.get("separator", ": ") or ": ")
                value = self._preview_metric_value(metric, subplot)
                lines.append(f"{label}{separator}{self._preview_format_metric(value, metric)}")
        text = "\n".join(lines)
        if not text.strip():
            return
        base_ax.text(
            float(info.get("x", 0.98) or 0.98),
            float(info.get("y", 0.98) or 0.98),
            text,
            transform=base_ax.transAxes,
            ha=str(info.get("ha", "right") or "right"),
            va=str(info.get("va", "top") or "top"),
            fontsize=float(info.get("font_size", max(7, self.project.style.font_size - 1)) or max(7, self.project.style.font_size - 1)),
            linespacing=float(info.get("linespacing", 1.2) or 1.2),
            bbox={
                "boxstyle": "square,pad=0.45",
                "facecolor": str(info.get("facecolor", self.project.style.axes_facecolor) or self.project.style.axes_facecolor),
                "edgecolor": str(info.get("edgecolor", self.project.style.text_color) or self.project.style.text_color),
                "linewidth": float(info.get("linewidth", 1.0) or 1.0),
                "alpha": float(info.get("alpha", 0.96) or 0.96),
            },
        )

    def render_subplot_horizontal_lines(self, base_ax, subplot: SubplotModel, axis_map: dict[str, Any]) -> None:
        y_lines = [y_line for y_line in getattr(subplot, "y_lines", []) if getattr(y_line, "visible", True)]
        if not y_lines:
            return
        fallback_axis = next(iter(axis_map.values())) if axis_map else base_ax
        for idx, y_line in enumerate(y_lines):
            target_axis = axis_map.get(getattr(y_line, "axis_id", "") or "") or fallback_axis
            color = getattr(y_line, "color", "#667085") or "#667085"
            line_style = getattr(y_line, "line_style", "--") or "--"
            line_width = float(getattr(y_line, "line_width", 1.0) or 1.0)
            alpha = max(0.0, min(1.0, float(getattr(y_line, "alpha", 0.9) or 0.9)))
            try:
                y_value = float(getattr(y_line, "y", 0.0) or 0.0)
            except Exception:
                continue
            try:
                target_axis.axhline(y=y_value, color=color, linestyle=line_style, linewidth=line_width, alpha=alpha, zorder=0)
            except Exception:
                continue
            label = str(getattr(y_line, "label", "") or "").strip()
            if label and getattr(y_line, "show_label", True):
                x_pos = max(0.0, min(1.0, float(getattr(y_line, "label_x", 0.99) or 0.99)))
                fontsize = float(getattr(y_line, "label_font_size", max(7, self.project.style.font_size - 2)) or max(7, self.project.style.font_size - 2))
                facecolor = str(getattr(y_line, "label_bg_color", self.project.style.axes_facecolor) or self.project.style.axes_facecolor)
                edgecolor = str(getattr(y_line, "label_border_color", "none") or "none")
                bg_alpha = max(0.0, min(1.0, float(getattr(y_line, "label_bg_alpha", min(1.0, alpha * 0.85)) or min(1.0, alpha * 0.85))))
                ha = str(getattr(y_line, "label_ha", "right") or "right")
                label_position = str(getattr(y_line, "label_position", "above") or "above").strip().lower()
                if label_position not in {"above", "below", "center"}:
                    label_position = "above"
                try:
                    label_offset_pt = float(getattr(y_line, "label_offset_pt", 3.0) or 0.0)
                except Exception:
                    label_offset_pt = 3.0
                if label_position == "below":
                    va = "top"
                    dy_pt = -abs(label_offset_pt)
                elif label_position == "center":
                    va = "center"
                    dy_pt = 0.0
                else:
                    va = "bottom"
                    dy_pt = abs(label_offset_pt)
                base_transform = mtransforms.blended_transform_factory(target_axis.transAxes, target_axis.transData)
                offset_transform = mtransforms.ScaledTranslation(0.0, dy_pt / 72.0, target_axis.figure.dpi_scale_trans)
                transform = base_transform + offset_transform
                target_axis.text(x_pos, y_value, label, transform=transform, ha=ha, va=va, fontsize=fontsize, color=color,
                                 bbox={"facecolor": facecolor, "edgecolor": edgecolor, "alpha": bg_alpha, "pad": 0.6})

    def render_regular_subplot(self, base_ax, subplot: SubplotModel, axis_map: dict[str, Any], subplot_index: int) -> list[PreviewSeriesTarget]:
        artist_targets: list[PreviewSeriesTarget] = []
        if not subplot.series:
            base_ax.text(0.5, 0.5, "No series", ha="center", va="center", transform=base_ax.transAxes, color=self.project.style.text_color)
            return artist_targets
        handles = []
        labels = []
        theta_data_min: float | None = None
        theta_data_max: float | None = None
        for series in subplot.series:
            if not series.visible:
                continue
            y_values, why = self.resolve_series_values(series.signal_key)
            if y_values is None:
                base_ax.text(0.02, 0.96 - 0.05 * len(labels), f"{series.signal_key}: {why}", transform=base_ax.transAxes, ha="left", va="top", color="#b42318")
                continue
            n = len(y_values)
            x_values, _ = self.resolve_x_values(subplot.x_signal, n)
            if x_values is None:
                x_values = [float(i) for i in range(n)]
            x_values = transform_values(x_values, getattr(subplot, "x_unit_preset", "raw"), getattr(subplot, "x_scale_factor", 1.0), getattr(subplot, "x_offset", 0.0)) or []
            y_values = transform_values(y_values, getattr(series, "unit_preset", "raw"), series.scale_factor, series.offset) or []
            x_num, y_num = align_numeric_pairs(x_values, y_values, scale=1.0, offset=0.0)
            if not x_num or not y_num:
                continue
            ax = axis_map.get(series.axis_id) or next(iter(axis_map.values()))
            if self._is_theta_subplot(subplot):
                x_clip_min, x_clip_max = self._theta_xlim_for_subplot(subplot)
                x_num = [min(max(float(v), x_clip_min), x_clip_max) for v in x_num]
                if x_num:
                    series_min = min(x_num)
                    series_max = max(x_num)
                    theta_data_min = series_min if theta_data_min is None else min(theta_data_min, series_min)
                    theta_data_max = series_max if theta_data_max is None else max(theta_data_max, series_max)
            label = series.label or series.signal_key
            plot_kwargs = dict(label=label, color=series.color, linewidth=series.line_width or self.project.style.default_line_width)
            if series.marker:
                plot_kwargs["marker"] = series.marker
                plot_kwargs["markersize"] = series.marker_size or self.project.style.default_marker_size
            if series.line_style:
                plot_kwargs["linestyle"] = series.line_style
            artist = None
            plotted_artists = []
            try:
                if series.series_type == "scatter":
                    artist = ax.scatter(x_num, y_num, label=label, color=series.color, s=max(8.0, (series.marker_size or 4.0) ** 2))
                    plotted_artists = [artist]
                else:
                    segments = [(list(x_num), list(y_num))]
                    if self._is_theta_subplot(subplot):
                        cycle_type = str(((self.config_data.get('engine') or {}).get('cycle_type') or '4T')).upper()
                        cycle_span = 360.0 if cycle_type == '2T' else 720.0
                        segments = self._split_theta_segments(list(x_num), list(y_num), cycle_span)
                    if series.series_type == "step":
                        artists = []
                        for seg_idx, (seg_x, seg_y) in enumerate(segments):
                            if not seg_x or not seg_y:
                                continue
                            seg_kwargs = dict(plot_kwargs)
                            if seg_idx > 0:
                                seg_kwargs.pop('label', None)
                            artists.append(ax.step(seg_x, seg_y, where="mid", **seg_kwargs)[0])
                        plotted_artists = artists
                        artist = artists[0] if artists else None
                    else:
                        artists = []
                        for seg_idx, (seg_x, seg_y) in enumerate(segments):
                            if not seg_x or not seg_y:
                                continue
                            seg_kwargs = dict(plot_kwargs)
                            if seg_idx > 0:
                                seg_kwargs.pop('label', None)
                            artists.append(ax.plot(seg_x, seg_y, **seg_kwargs)[0])
                        plotted_artists = artists
                        artist = artists[0] if artists else None
            except Exception as exc:
                base_ax.text(0.02, 0.9 - 0.05 * len(labels), f"Plot error {label}: {exc}", transform=base_ax.transAxes, ha="left", va="top", color="#b42318")
            if artist is not None:
                for plotted_artist in plotted_artists or [artist]:
                    try:
                        if hasattr(plotted_artist, "set_pickradius"):
                            plotted_artist.set_pickradius(6)
                        if hasattr(plotted_artist, "set_picker"):
                            plotted_artist.set_picker(True)
                    except Exception:
                        pass
                handles.append(artist)
                labels.append(label)
                for plotted_artist in plotted_artists or [artist]:
                    artist_targets.append(PreviewSeriesTarget(artist=plotted_artist, subplot_index=subplot_index, series_id=series.id, label=label, color=series.color or "#1f77b4", x_values=list(x_num), y_values=list(y_num)))
        if self._is_theta_subplot(subplot) and getattr(subplot, 'x_limit_mode', 'data') != 'manual' and theta_data_min is not None and theta_data_max is not None:
            if getattr(subplot, 'x_start_at_zero', True):
                theta_data_min = 0.0
            if abs(theta_data_max - theta_data_min) < 1.0e-12:
                theta_data_max = theta_data_min + 1.0
            base_ax.set_xlim(theta_data_min, theta_data_max)
        elif getattr(subplot, 'x_limit_mode', 'data') != 'manual' and getattr(subplot, 'x_start_at_zero', True):
            x_max_data = None
            for series in subplot.series:
                if not getattr(series, 'visible', True):
                    continue
                y_values, _why = self.resolve_series_values(series.signal_key)
                if y_values is None:
                    continue
                n = len(y_values)
                x_values, _ = self.resolve_x_values(subplot.x_signal, n)
                if x_values is None:
                    x_values = [float(i) for i in range(n)]
                x_values = transform_values(x_values, getattr(subplot, "x_unit_preset", "raw"), getattr(subplot, "x_scale_factor", 1.0), getattr(subplot, "x_offset", 0.0)) or []
                valid_x = [float(v) for v in x_values if v is not None]
                if valid_x:
                    series_max = max(valid_x)
                    x_max_data = series_max if x_max_data is None else max(x_max_data, series_max)
            if x_max_data is not None:
                if abs(x_max_data) < 1.0e-12:
                    x_max_data = 1.0
                base_ax.set_xlim(0.0, x_max_data)
        if subplot.legend_visible and self.project.style.legend_visible and handles:
            legend = base_ax.legend(handles, labels, loc=subplot.legend_position or self.project.style.legend_position)
            if legend:
                legend.get_frame().set_facecolor(self.project.style.legend_facecolor)
                legend.get_frame().set_edgecolor(self.project.style.legend_edgecolor)
                for text in legend.get_texts():
                    text.set_color(self.project.style.text_color)
        for axis_model in getattr(subplot, "y_axes", []) or []:
            mpl_axis = axis_map.get(axis_model.id)
            if mpl_axis is not None:
                self._apply_axis_view_config(mpl_axis, axis_model)
        return artist_targets

    def render_timing_subplot(self, ax, subplot: SubplotModel) -> None:
        cycle = str(((self.config_data.get("engine") or {}).get("cycle_type") or "4T")).upper()
        span = 360 if cycle == "2T" else 720
        theta = [float(i) for i in range(span + 1)]
        mode = str(((self.config_data.get("gasexchange") or {}).get("mode") or "valves"))
        intake, exhaust = self.compute_timing_curves(theta, mode)
        if subplot.plot_type == "timing_polar":
            th = [math.radians(t) for t in theta]
            ax.plot(th, intake, color="#1f77b4", linewidth=2.0, label="Intake")
            ax.plot(th, exhaust, color="#d62728", linewidth=2.0, label="Exhaust")
            ax.set_theta_zero_location("N")
            ax.set_theta_direction(-1)
            if getattr(subplot, "show_title", True) and self.project.style.subplot_title_visible:
                ax.set_title(subplot.title or "Timing Polar", color=self.project.style.text_color, fontsize=self.project.style.title_size)
            else:
                ax.set_title("")
        else:
            theta_plot = transform_values(theta, getattr(subplot, "x_unit_preset", "raw"), getattr(subplot, "x_scale_factor", 1.0), getattr(subplot, "x_offset", 0.0)) or theta
            ax.plot(theta_plot, intake, color="#1f77b4", linewidth=2.0, label="Intake")
            ax.plot(theta_plot, exhaust, color="#d62728", linewidth=2.0, label="Exhaust")
            ax.set_xlabel(axis_title_with_unit(subplot.x_title or "Theta", getattr(subplot, "x_unit_preset", "raw")), color=self.project.style.text_color, fontsize=self.project.style.axis_label_size)
            ax.set_ylabel("Opening", color=self.project.style.text_color, fontsize=self.project.style.axis_label_size)
            if getattr(subplot, "x_limit_mode", "data") == "manual":
                ax.set_xlim(float(getattr(subplot, "x_min", 0.0)), float(getattr(subplot, "x_max", 1.0)))
            elif getattr(subplot, "x_start_at_zero", True):
                ax.set_xlim(0.0, float(span))
            ax.xaxis.set_major_locator(MultipleLocator(180.0))
            ax.xaxis.set_minor_locator(MultipleLocator(60.0))
            if self.project.style.grid_visible and subplot.show_grid:
                ax.grid(True, which='major', color=self.project.style.grid_color, alpha=max(self.project.style.grid_alpha, 0.35))
                ax.grid(True, which='minor', color=self.project.style.grid_color, alpha=min(self.project.style.grid_alpha, 0.22))
            if getattr(subplot, "y_axes", None):
                self._apply_axis_view_config(ax, subplot.y_axes[0])
            if getattr(subplot, "show_title", True) and self.project.style.subplot_title_visible:
                ax.set_title(subplot.title or "Timing", color=self.project.style.text_color, fontsize=self.project.style.title_size)
            else:
                ax.set_title("")
        if subplot.legend_visible:
            legend = ax.legend(loc=subplot.legend_position or self.project.style.legend_position)
            if legend:
                legend.get_frame().set_facecolor(self.project.style.legend_facecolor)
                legend.get_frame().set_edgecolor(self.project.style.legend_edgecolor)
                for text in legend.get_texts():
                    text.set_color(self.project.style.text_color)

    def compute_timing_curves(self, theta: list[float], mode: str) -> tuple[list[float], list[float]]:
        if mode == "valves":
            return self.compute_valve_timing(theta)
        if mode == "ports":
            return self.compute_window_timing(theta, base_path=("ports",))
        if mode == "slots":
            return self.compute_window_timing(theta, base_path=("slots",))
        return [0.0 for _ in theta], [0.0 for _ in theta]

    def compute_valve_timing(self, theta: list[float]) -> tuple[list[float], list[float]]:
        cfg = (self.config_data.get("gasexchange") or {}).get("valves") or {}
        cycle = str(((self.config_data.get("engine") or {}).get("cycle_type") or "4T")).upper()
        span = 360 if cycle == "2T" else 720
        curves: list[list[float]] = []
        for side in ["intake", "exhaust"]:
            side_cfg = cfg.get(side) or {}
            center = float(side_cfg.get("center_deg", 0.0) or 0.0)
            open_deg = float(side_cfg.get("open_deg", 0.0) or 0.0)
            close_deg = float(side_cfg.get("close_deg", open_deg) or open_deg)
            duration = max(close_deg - open_deg, 0.0)
            max_lift = max(float(side_cfg.get("max_lift_m", 1.0) or 1.0), 1e-9)
            values = []
            for t in theta:
                delta = t - center
                while delta > span / 2:
                    delta -= span
                while delta < -span / 2:
                    delta += span
                if abs(delta) > duration / 2.0:
                    lift = 0.0
                else:
                    phase = (delta + duration / 2.0) / max(duration, 1e-9)
                    lift = 0.5 * (1.0 - math.cos(2 * math.pi * phase))
                values.append(lift / max_lift)
            curves.append(values)
        return curves[0], curves[1]

    def compute_window_timing(self, theta: list[float], base_path: tuple[str, ...]) -> tuple[list[float], list[float]]:
        gas_cfg = self.config_data.get("gasexchange") or {}
        engine_cfg = self.config_data.get("engine") or {}
        stroke = float(engine_cfg.get("stroke_m", 0.086) or 0.086)
        conrod = float(engine_cfg.get("conrod_m", 0.143) or 0.143)
        root = gas_cfg
        for part in base_path:
            root = root.get(part) or {}
        intake_values = self._compute_single_window(theta, root.get("intake") or {}, stroke, conrod)
        exhaust_values = self._compute_single_window(theta, root.get("exhaust") or {}, stroke, conrod)
        if base_path == ("slots",):
            intake_groups = root.get("intake_groups") or []
            exhaust_groups = root.get("exhaust_groups") or []
            if intake_groups:
                values = [[0.0 for _ in theta] for _ in intake_groups]
                for idx, group in enumerate(intake_groups):
                    values[idx] = self._compute_single_window(theta, group, stroke, conrod)
                intake_values = [max(vals) for vals in zip(*values)]
            if exhaust_groups:
                values = [[0.0 for _ in theta] for _ in exhaust_groups]
                for idx, group in enumerate(exhaust_groups):
                    values[idx] = self._compute_single_window(theta, group, stroke, conrod)
                exhaust_values = [max(vals) for vals in zip(*values)]
        return intake_values, exhaust_values

    def _compute_single_window(self, theta: list[float], cfg: dict[str, Any], stroke: float, conrod: float) -> list[float]:
        height = max(float(cfg.get("height_m", 0.0) or 0.0), 1e-12)
        offset_ut = max(float(cfg.get("offset_from_ut_m", 0.0) or 0.0), 0.0)
        roof = cfg.get("roof") or {}
        roof_type = str(roof.get("type") or "none")
        roof_len = float(roof.get("len_m", 0.0) or 0.0)
        roof_gamma = float(roof.get("gamma", 1.0) or 1.0)
        roof_angle = math.radians(float(roof.get("angle_deg", 0.0) or 0.0))
        out = []
        for t in theta:
            piston_from_ut = piston_distance_from_ut(stroke, conrod, t)
            open_height = piston_from_ut - offset_ut
            open_height = max(0.0, min(height, open_height))
            if open_height > 0.0 and roof_type != "none":
                if roof_type == "linear" and roof_len > 0:
                    roof_cut = min(open_height, roof_len)
                    open_height -= 0.5 * roof_cut
                elif roof_type == "cos" and roof_len > 0:
                    roof_cut = min(open_height, roof_len)
                    frac = roof_cut / roof_len
                    open_height -= 0.5 * roof_cut * (1 - math.cos(math.pi * frac))
                elif roof_type == "factor" and roof_len > 0:
                    roof_cut = min(open_height, roof_len)
                    frac = roof_cut / roof_len
                    open_height -= roof_cut * (frac ** max(0.01, roof_gamma)) * 0.5
                elif roof_type == "angle" and roof_angle > 1e-9:
                    roof_equiv = min(height, max(0.0, height * math.tan(roof_angle) * 0.25))
                    roof_cut = min(open_height, roof_equiv)
                    open_height -= 0.5 * roof_cut
            out.append(open_height / height)
        return out

    # ---------- close ----------
    def closeEvent(self, event) -> None:
        try:
            self.settings.setValue("window/geometry", self.saveGeometry())
            self.settings.setValue("window/state", self.saveState())
            self.settings.setValue("session/current_project_path", str(self.current_project_path or ""))
            self.settings.setValue("session/project_json", json.dumps(self.project_to_dict(), ensure_ascii=False))
            self.settings.setValue("session/config_path", self.project.config_path)
            self.settings.setValue("session/signals_path", self.project.signals_path)
            self.settings.setValue("session/preview_csv_path", self.project.preview_csv_path)
            self._store_plot_style_state()
        except Exception:
            pass
        super().closeEvent(event)


def piston_distance_from_ut(stroke_m: float, conrod_m: float, crank_deg: float) -> float:
    r = max(stroke_m * 0.5, 1e-12)
    l = max(conrod_m, r + 1e-9)
    theta = math.radians(crank_deg)
    y_tdc = r + l
    y = r * math.cos(theta) + math.sqrt(max(l * l - (r * math.sin(theta)) ** 2, 0.0))
    distance_from_tdc = y_tdc - y
    return stroke_m - distance_from_tdc


def scale_values(values: list[Any] | None, factor: float) -> list[Any] | None:
    if values is None:
        return None
    out: list[Any] = []
    for v in values:
        num = coerce_float(v)
        out.append(None if num is None else num * factor)
    return out


def coerce_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def align_numeric_pairs(x_values: list[Any], y_values: list[Any], scale: float = 1.0, offset: float = 0.0) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []
    for xv, yv in zip(x_values, y_values):
        x = coerce_float(xv)
        y = coerce_float(yv)
        if x is None or y is None:
            continue
        xs.append(x)
        ys.append(y * scale + offset)
    return xs, ys


def re_any(text: str, needles: list[str]) -> bool:
    return any(n in text for n in needles)


def next_color(index: int) -> str:
    palette = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b", "#e377c2"]
    return palette[index % len(palette)]



# ===== thermo0d plot integration helpers =====

def _plot_load_yaml_or_json(path: Path) -> dict[str, Any]:
    if path.suffix.lower() in {'.yaml', '.yml'}:
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    data = json.loads(path.read_text(encoding='utf-8'))
    return data if isinstance(data, dict) else {}


def _plot_detect_separator(path: Path) -> str:
    sample = path.read_text(encoding='utf-8-sig', errors='ignore')[:4096]
    counts = {';': sample.count(';'), ',': sample.count(','), '\t': sample.count('\t')}
    return max(counts.items(), key=lambda item: item[1])[0] if counts else ','


def _plot_plot_wrap_angle(angle_deg: float, cycle_deg: float) -> float:
    cycle = max(float(cycle_deg or 0.0), 1.0)
    out = float(angle_deg) % cycle
    if out < 0.0:
        out += cycle
    return out


def _plot_plot_reference_zero_deg(cycle_deg: float, reference: str) -> float:
    ref = str(reference or 'compression_tdc').strip().lower()
    if ref in {'absolute', 'compression_tdc'}:
        return 0.0
    if ref == 'gas_exchange_tdc':
        return 360.0 if float(cycle_deg) >= 719.0 else 0.0
    return 0.0


def _plot_plot_read_profile_angles(profile_path: Path) -> list[tuple[float, float]]:
    if not profile_path.exists():
        return []
    delimiter = _plot_detect_separator(profile_path)
    rows: list[tuple[float, float]] = []
    with profile_path.open('r', encoding='utf-8-sig', newline='') as handle:
        reader = csv.reader(handle, delimiter=delimiter)
        for raw in reader:
            if not raw or len(raw) < 2:
                continue
            x = coerce_float(raw[0])
            y = coerce_float(raw[1])
            if x is None or y is None:
                continue
            rows.append((float(x), float(y)))
    return rows


def _plot_plot_event_model(x_value: float, label: str, color: str = '#666666', line_style: str = ':', line_width: float = 1.0, alpha: float = 0.9, visible: bool = True, show_label: bool = True, source: str = 'config_auto', source_note: str = 'Automatisch aus aktiver Config erzeugt', locked: bool = False, event_type: str = 'custom') -> EventModel:
    return EventModel(x=float(x_value), label=str(label), color=str(color), line_style=str(line_style), line_width=float(line_width), alpha=float(alpha), visible=bool(visible), show_label=bool(show_label), source=str(source), source_note=str(source_note), locked=bool(locked), event_type=str(event_type), label_bg_color='#ffffff', label_border_color='none')


def _plot_plot_generate_events_from_config(config_data: dict[str, Any] | None, config_path: str | Path | None, selected_cylinder: str = '') -> list[EventModel]:
    cfg = config_data if isinstance(config_data, dict) else {}
    prep = cfg.get('preprocessing', {}) if isinstance(cfg.get('preprocessing', {}), dict) else {}
    engine = prep.get('engine', {}) if isinstance(prep.get('engine', {}), dict) else {}
    volumes = prep.get('volumes', []) if isinstance(prep.get('volumes', []), list) else []
    connections = prep.get('connections', []) if isinstance(prep.get('connections', []), list) else []
    cycle_type = str(engine.get('cycle_type', '4t')).strip().lower()
    cycle_deg = 720.0 if cycle_type == '4t' else 360.0
    cylinder_name = str(selected_cylinder or '').strip()
    if not cylinder_name:
        for volume in volumes:
            if isinstance(volume, dict) and str(volume.get('type', '')).strip().lower() == 'cylinder':
                cylinder_name = str(volume.get('name', '')).strip()
                if cylinder_name:
                    break
    base_dir = Path(config_path).resolve().parent if config_path else Path.cwd()
    events: list[EventModel] = []

    if cycle_deg >= 719.0:
        events.extend([
            _plot_plot_event_model(0.0, 'OT', color='#667085', line_style=':', event_type='reference'),
            _plot_plot_event_model(180.0, 'UT', color='#667085', line_style=':', event_type='reference'),
            _plot_plot_event_model(360.0, 'OT', color='#98a2b3', line_style=':', event_type='reference'),
            _plot_plot_event_model(540.0, 'UT', color='#98a2b3', line_style=':', event_type='reference'),
        ])
    else:
        events.extend([
            _plot_plot_event_model(0.0, 'OT', color='#667085', line_style=':', event_type='reference'),
            _plot_plot_event_model(cycle_deg * 0.5, 'UT', color='#667085', line_style=':', event_type='reference'),
        ])

    for conn in connections:
        if not isinstance(conn, dict) or str(conn.get('type', '')).strip().lower() != 'valve':
            continue
        from_volume = str(conn.get('from_volume', '')).strip()
        to_volume = str(conn.get('to_volume', '')).strip()
        is_intake = bool(cylinder_name) and to_volume == cylinder_name and from_volume != cylinder_name
        is_exhaust = bool(cylinder_name) and from_volume == cylinder_name and to_volume != cylinder_name
        if not is_intake and not is_exhaust:
            low_from = from_volume.lower()
            low_to = to_volume.lower()
            if 'cyl' in low_to and 'cyl' not in low_from:
                is_intake = True
            elif 'cyl' in low_from and 'cyl' not in low_to:
                is_exhaust = True
        if not is_intake and not is_exhaust:
            continue
        label_open = 'IVO' if is_intake else 'EVO'
        label_close = 'IVC' if is_intake else 'EVC'
        color = '#175cd3' if is_intake else '#b42318'
        opening_angle = float(conn.get('opening_angle_deg', 0.0) or 0.0)
        opening_reference = str(conn.get('opening_reference', 'compression_tdc') or 'compression_tdc')
        local_profile = _plot_plot_read_profile_angles((base_dir / str(conn.get('lift_file', ''))).resolve()) if conn.get('lift_file') else []
        local_open = 0.0
        local_close = 0.0
        if local_profile:
            lift_scale = float(conn.get('lift_scale', 1.0) or 1.0)
            lash = float(conn.get('lash_m', 0.0) or 0.0)
            domain = str(conn.get('profile_angle_domain', 'crank') or 'crank').strip().lower()
            positive = [(ang, val * lift_scale - lash) for ang, val in local_profile if val * lift_scale - lash > 1.0e-12]
            if positive:
                local_open = float(positive[0][0])
                local_close = float(positive[-1][0])
                if domain != 'crank':
                    cam_ratio = cycle_deg / 360.0
                    local_open *= cam_ratio
                    local_close *= cam_ratio
        angle0 = _plot_plot_reference_zero_deg(cycle_deg, opening_reference) + opening_angle
        events.append(_plot_plot_event_model(_plot_plot_wrap_angle(angle0 + local_open, cycle_deg), label_open, color=color, event_type='valve'))
        events.append(_plot_plot_event_model(_plot_plot_wrap_angle(angle0 + local_close, cycle_deg), label_close, color=color, event_type='valve'))

    for volume in volumes:
        if not isinstance(volume, dict):
            continue
        vol_name = str(volume.get('name', '')).strip()
        if cylinder_name and vol_name and vol_name != cylinder_name:
            continue
        combustion = volume.get('combustion', {}) if isinstance(volume.get('combustion', {}), dict) else {}
        model = str(combustion.get('model', 'none')).strip().lower()
        if model and model != 'none':
            ref0 = _plot_plot_reference_zero_deg(cycle_deg, str(combustion.get('angle_reference', 'compression_tdc') or 'compression_tdc'))
            start = _plot_plot_wrap_angle(ref0 + float(combustion.get('start_deg', 0.0) or 0.0), cycle_deg)
            end = _plot_plot_wrap_angle(start + float(combustion.get('duration_deg', 0.0) or 0.0), cycle_deg)
            events.append(_plot_plot_event_model(start, 'SOC', color='#f79009', line_style='--', event_type='combustion'))
            events.append(_plot_plot_event_model(end, 'EOC', color='#f79009', line_style='--', event_type='combustion'))
        evaporation = volume.get('evaporation', {}) if isinstance(volume.get('evaporation', {}), dict) else {}
        evap_model = str(evaporation.get('model', 'none')).strip().lower()
        if evap_model and evap_model != 'none':
            ref0 = _plot_plot_reference_zero_deg(cycle_deg, str(evaporation.get('angle_reference', 'compression_tdc') or 'compression_tdc'))
            start = _plot_plot_wrap_angle(ref0 + float(evaporation.get('start_deg', 0.0) or 0.0), cycle_deg)
            end = _plot_plot_wrap_angle(start + float(evaporation.get('duration_deg', 0.0) or 0.0), cycle_deg)
            events.append(_plot_plot_event_model(start, 'SOI', color='#12b76a', line_style='--'))
            events.append(_plot_plot_event_model(end, 'EOI', color='#12b76a', line_style='--'))
        if cylinder_name and vol_name == cylinder_name:
            break

    dedup: dict[tuple[str, float], EventModel] = {}
    for event in events:
        key = (str(event.label), round(float(event.x), 6))
        dedup[key] = event
    return [dedup[key] for key in sorted(dedup.keys(), key=lambda item: item[1])]


def _plot_default_headers(headers: list[str]) -> dict[str, list[str]]:
    ordered = [str(h) for h in headers if h]
    return {
        'minimal': ordered[: min(len(ordered), 12)] or ordered,
        'full': ordered,
        'postprocessed_dataframe_columns': ordered,
        'plotting_series_aliases': [
            'theta_deg', 'theta_local_deg', 'p_cyl_pa', 'p_cyl_bar', 'V_m3', 'V_cm3', 'A_in_mm2', 'A_ex_mm2'
        ],
        'default_plot_style_keys': [
            'theta_deg', 'p_cyl_pa', 'cylinder_theta_deg', 'cylinder_p_Pa', 'cylinder_V_m3',
            'cylinder_T_K', 'intake_valve_A_eff_forward_m2', 'exhaust_valve_A_eff_forward_m2'
        ],
    }


def _plot_build_catalog_from_csv(self) -> None:
    if self.preview_csv.headers:
        self.catalog.raw = _plot_default_headers(self.preview_csv.headers)
        self.catalog.error = ''
        self.catalog.available_set = set(self.preview_csv.headers)


def _plot_default_x_signal(self) -> str:
    headers = set(self.preview_csv.headers)
    for candidate in ('cylinder_theta_deg', 'theta_deg', 'theta_local_deg'):
        if candidate in headers:
            return candidate
    return 'cylinder_theta_deg'


def _plot_default_y_signal(self) -> str:
    headers = set(self.preview_csv.headers)
    for candidate in ('cylinder_p_Pa', 'p_cyl_pa', 'cylinder_T_K', 'cylinder_V_m3'):
        if candidate in headers:
            return candidate
    return 'cylinder_p_Pa'


def _plot_plot_validate_signal_catalog_path(self, path: Path) -> None:
    return None


def _plot_plot_load_config_from_path(self, path: Path, silent: bool = False) -> None:
    try:
        self.config_data = _plot_load_yaml_or_json(path)
    except Exception as exc:
        show_critical(self, 'Config laden', str(exc))
        return
    if isinstance(self.config_data, dict) and requires_version_upgrade(self.config_data):
        loaded_schema = config_schema_version_from_document(self.config_data)
        answer = ask_question(
            self,
            'Alte Konfigurationsversion',
            build_upgrade_message(path, loaded_schema),
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button=QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            try:
                self.config_data = migrate_config_file_in_place(path, self.config_data)
                if not silent:
                    self.statusBar().showMessage(
                        f'Konfigurationsversion aktualisiert: Schema {loaded_schema} → {CURRENT_CONFIG_SCHEMA_VERSION}',
                        5000,
                    )
            except Exception as exc:
                show_critical(self, 'Versionsupdate fehlgeschlagen', str(exc))
                return
    self.project.config_path = str(path)
    self.settings.setValue('session/config_path', str(path))
    detected = self.detected_cylinders()
    if detected and self.project.selected_cylinder not in detected:
        self.project.selected_cylinder = detected[0]
    self.refresh_cylinder_combo()
    self._autofill_events_from_config(overwrite=False, scope="all")
    self.update_diagnosis()
    self.populate_signal_tree()
    self.set_dirty()
    if not silent:
        self.statusBar().showMessage(f'Config geladen: {path}', 2500)


def _plot_plot_load_signals_from_path(self, path: Path, silent: bool = False) -> None:
    try:
        self.catalog.load(str(path))
        self.project.signals_path = str(path)
        self.signals_path_label.setText(str(path))
        self.settings.setValue('session/signals_path', str(path))
    except Exception as exc:
        self.catalog.error = str(exc)
    if not self.catalog.raw and self.preview_csv.headers:
        _plot_build_catalog_from_csv(self)
    self.populate_signal_tree()
    self.update_diagnosis()
    self.set_dirty()
    if not silent:
        self.statusBar().showMessage(f'Signals geladen: {path}', 2500)


def _plot_prefer_uniform_preview_csv_enabled(self) -> bool:
    raw = self.settings.value('session/prefer_uniform_preview_csv', True)
    if isinstance(raw, bool):
        return raw
    return str(raw).strip().lower() not in {'0', 'false', 'no', 'off'}


def _plot_set_prefer_uniform_preview_csv(self, enabled: bool) -> None:
    self.settings.setValue('session/prefer_uniform_preview_csv', bool(enabled))
    if hasattr(self, 'action_prefer_uniform_preview_csv') and self.action_prefer_uniform_preview_csv is not None:
        blocked = self.action_prefer_uniform_preview_csv.blockSignals(True)
        self.action_prefer_uniform_preview_csv.setChecked(bool(enabled))
        self.action_prefer_uniform_preview_csv.blockSignals(blocked)
    if hasattr(self, 'prefer_uniform_preview_check') and self.prefer_uniform_preview_check is not None:
        blocked = self.prefer_uniform_preview_check.blockSignals(True)
        self.prefer_uniform_preview_check.setChecked(bool(enabled))
        self.prefer_uniform_preview_check.blockSignals(blocked)
    self.update_statusbar()


def _plot_toggle_preferred_preview_csv_mode(self, enabled: bool) -> None:
    _plot_set_prefer_uniform_preview_csv(self, bool(enabled))
    active_path = str(self.project.preview_csv_path or getattr(self, '_preview_csv_requested_path', '') or '')
    if active_path:
        try:
            self.load_preview_csv_from_path(Path(active_path), silent=True)
            mode_text = 'uniform bevorzugt' if enabled else 'Original-CSV erzwungen'
            self.statusBar().showMessage(f'Preview-Modus: {mode_text}', 2500)
        except Exception:
            pass


def _plot_build_actions_with_uniform_toggle(self) -> None:
    _ORIG_BUILD_ACTIONS(self)
    self.action_prefer_uniform_preview_csv = QAction('Uniform-CSV bevorzugen', self)
    self.action_prefer_uniform_preview_csv.setCheckable(True)
    self.action_prefer_uniform_preview_csv.setToolTip('Wenn neben der normalen Ergebnisdatei eine *_last_cycle_uniform.csv existiert, wird diese für die Preview bevorzugt.')
    self.action_prefer_uniform_preview_csv.toggled.connect(lambda checked: _plot_toggle_preferred_preview_csv_mode(self, checked))
    _plot_set_prefer_uniform_preview_csv(self, _plot_prefer_uniform_preview_csv_enabled(self))


def _plot_build_menus_with_uniform_toggle(self) -> None:
    _ORIG_BUILD_MENUS(self)
    if hasattr(self, 'view_menu') and self.view_menu is not None:
        self.view_menu.addSeparator()
        self.view_menu.addAction(self.action_prefer_uniform_preview_csv)


def _plot_build_toolbar_with_uniform_toggle(self) -> None:
    _ORIG_BUILD_TOOLBAR(self)
    bars = self.findChildren(QToolBar)
    if not bars:
        return
    bar = bars[0]
    bar.addSeparator()
    button = QToolButton()
    button.setAutoRaise(True)
    button.setCheckable(True)
    button.setDefaultAction(self.action_prefer_uniform_preview_csv)
    bar.addWidget(button)


def _plot_build_signals_panel_with_uniform_toggle(self):
    root = _ORIG_BUILD_SIGNALS_PANEL(self)
    self.prefer_uniform_preview_check = QCheckBox('Uniform-CSV bevorzugen')
    self.prefer_uniform_preview_check.setToolTip('Nutze für die Preview automatisch die *_last_cycle_uniform.csv, falls sie neben der normalen CSV existiert.')
    self.prefer_uniform_preview_check.toggled.connect(lambda checked: _plot_toggle_preferred_preview_csv_mode(self, checked))
    _plot_set_prefer_uniform_preview_csv(self, _plot_prefer_uniform_preview_csv_enabled(self))
    group_boxes = root.findChildren(QGroupBox)
    if group_boxes:
        form = group_boxes[0].layout()
        if isinstance(form, QFormLayout):
            form.addRow('CSV-Auswahl', self.prefer_uniform_preview_check)
    return root


def _plot_update_statusbar_with_uniform_mode(self) -> None:
    status_attrs = ('status_project', 'status_config', 'status_signals', 'status_csv', 'status_detect')
    if not all(hasattr(self, attr) and getattr(self, attr) is not None for attr in status_attrs):
        return
    _ORIG_UPDATE_STATUSBAR(self)
    prefer_uniform = _plot_prefer_uniform_preview_csv_enabled(self)
    resolved_path = str(getattr(self, '_preview_csv_resolved_path', '') or self.project.preview_csv_path or '')
    requested_path = str(getattr(self, '_preview_csv_requested_path', '') or '')
    if hasattr(self, 'status_csv') and self.status_csv is not None:
        suffix = ' | prefer uniform' if prefer_uniform else ' | original csv'
        self.status_csv.setText(self.status_csv.text() + suffix)
        tooltip = self.status_csv.toolTip() or ''
        if requested_path and resolved_path:
            tooltip += f"\nModus: {'uniform bevorzugt' if prefer_uniform else 'Original-CSV erzwingen'}"
        self.status_csv.setToolTip(tooltip.strip())



def _plot_resolve_preferred_preview_csv(path: Path, prefer_uniform: bool = True) -> tuple[Path, str]:
    requested = Path(path).expanduser().resolve()
    if not requested.exists():
        return requested, "missing"
    name_lower = requested.name.lower()
    if name_lower.endswith('_last_cycle_uniform.csv'):
        if prefer_uniform:
            return requested, "uniform"
        base_name = requested.name[:-len('_last_cycle_uniform.csv')] + '.csv'
        direct_candidate = requested.with_name(base_name)
        if direct_candidate.exists():
            return direct_candidate, f"original CSV forced instead of {requested.name}"
        return requested, "uniform (original missing)"
    if requested.suffix.lower() == '.csv' and prefer_uniform:
        uniform_candidate = requested.with_name(requested.stem + '_last_cycle_uniform.csv')
        if uniform_candidate.exists():
            return uniform_candidate, f"preferred uniform last-cycle CSV next to {requested.name}"
    return requested, "direct"


def _plot_set_preview_csv_resolution_state(self, requested_path: Path, actual_path: Path, reason: str) -> None:
    self._preview_csv_requested_path = str(requested_path)
    self._preview_csv_resolution_reason = str(reason)
    self._preview_csv_resolved_path = str(actual_path)
    if hasattr(self, 'csv_path_label') and self.csv_path_label is not None:
        tooltip = f"Aktiv für Preview: {actual_path}"
        if requested_path != actual_path:
            tooltip += f"\nAngefordert: {requested_path}\nAuswahlregel: {reason}"
        self.csv_path_label.setToolTip(tooltip)


def _plot_plot_load_preview_csv_from_path(self, path: Path, silent: bool = False) -> None:
    requested_path = Path(path).expanduser()
    actual_path, reason = _plot_resolve_preferred_preview_csv(requested_path, prefer_uniform=_plot_prefer_uniform_preview_csv_enabled(self))
    self.preview_csv.load(str(actual_path))
    self.project.preview_csv_path = str(actual_path)
    self.csv_path_label.setText(str(actual_path))
    self.settings.setValue('session/preview_csv_path', str(actual_path))
    _plot_set_preview_csv_resolution_state(self, requested_path, actual_path, reason)
    detected_from_preview = self.detected_cylinders_from_preview()
    if detected_from_preview and self.project.selected_cylinder not in detected_from_preview:
        self.project.selected_cylinder = detected_from_preview[0]
    self.refresh_cylinder_combo()
    if not self.catalog.raw:
        _plot_build_catalog_from_csv(self)
    self.populate_signal_tree()
    self.update_diagnosis()
    self.set_dirty()
    if not silent:
        if requested_path.resolve() != actual_path.resolve():
            self.statusBar().showMessage(f'CSV geladen: {actual_path.name} (bevorzugt statt {requested_path.name})', 3500)
        else:
            self.statusBar().showMessage(f'CSV geladen: {actual_path}', 2500)


def _plot_plot_auto_open_defaults(self) -> None:
    script_dir = Path(__file__).resolve().parent
    env_project_dir = Path(os.getenv('THERMO0D_DEFAULT_PROJECT') or os.getenv('MOTORSIM_PROJECT_DIR') or Path.cwd()).expanduser().resolve()
    code_root = find_code_root(env_project_dir)
    project_paths = build_paths(project_dir=env_project_dir)

    stored_project = str(self.settings.value('session/current_project_path', '') or '')
    stored_signals = str(self.settings.value('session/signals_path', '') or '')
    stored_config = str(self.settings.value('session/config_path', '') or '')
    stored_csv = str(self.settings.value('session/preview_csv_path', '') or '')

    if stored_project and Path(stored_project).exists():
        self.load_project_from_path(Path(stored_project), silent=True)
    else:
        for candidate in (env_project_dir / DEFAULT_PROJECT_YAML, env_project_dir / 'plot.yml'):
            if candidate.exists():
                self.load_project_from_path(candidate, silent=True)
                break

    config_candidates: list[Path] = []
    if stored_config:
        config_candidates.append(Path(stored_config))
    config_candidates.extend([
        project_paths.project_config_file,
        default_config_file(code_root),
        env_project_dir / 'config.yaml',
        env_project_dir / 'config.yml',
        script_dir / 'config.yaml',
        Path.cwd() / 'config.yaml',
    ])
    config_candidate = next((p for p in config_candidates if p.exists()), None)
    if config_candidate:
        self.load_config_from_path(config_candidate, silent=True)

    csv_candidates: list[Path] = []
    if stored_csv:
        csv_candidates.append(Path(stored_csv))
    if config_candidate and isinstance(self.config_data, dict):
        post = dict(self.config_data.get('postprocessing') or {})
        csv_path = post.get('csv_path')
        if csv_path:
            resolved_csv = PathManager.resolve_output_file(
                config_candidate,
                configured_outdir=post.get('outdir'),
                configured_path=str(csv_path),
                fallback_name='out.csv',
            )
            resolved_uniform, _ = _plot_resolve_preferred_preview_csv(resolved_csv, prefer_uniform=_plot_prefer_uniform_preview_csv_enabled(self))
            csv_candidates.append(resolved_uniform)
            csv_candidates.append(resolved_csv)
    csv_candidates.extend([
        project_paths.project_out_dir / 'out_gui_last_cycle_uniform.csv',
        project_paths.project_out_dir / 'out_gui.csv',
        project_paths.project_dir / 'out_gui_last_cycle_uniform.csv',
        project_paths.project_dir / 'out_gui.csv',
        env_project_dir / 'results' / 'output_last_cycle_uniform.csv',
        env_project_dir / 'results' / 'output.csv',
        env_project_dir / 'results' / 'one_cyl_4t_last_cycle_uniform.csv',
        env_project_dir / 'results' / 'one_cyl_4t.csv',
        env_project_dir / 'results' / 'one_cyl_2t_last_cycle_uniform.csv',
        env_project_dir / 'results' / 'one_cyl_2t.csv',
    ])
    csv_candidate = next((p for p in csv_candidates if p.exists()), None)
    if csv_candidate:
        self.load_preview_csv_from_path(csv_candidate, silent=True)

    signal_candidates: list[Path] = []
    if stored_signals:
        signal_candidates.append(Path(stored_signals))
    signal_candidates.extend([
        env_project_dir / 'thermo0d_signal_catalog.json',
        env_project_dir / DEFAULT_SIGNALS_JSON,
        script_dir / 'thermo0d_signal_catalog.json',
        script_dir / DEFAULT_SIGNALS_JSON,
        code_root / 'scripts' / 'thermo0d_signal_catalog.json',
    ])
    signals_candidate = next((p for p in signal_candidates if p.exists()), None)
    if signals_candidate:
        self.load_signals_from_path(signals_candidate, silent=True)
    elif self.preview_csv.headers:
        _plot_build_catalog_from_csv(self)

    session_json = str(self.settings.value('session/project_json', '') or '')
    if not self.project.figures and session_json:
        try:
            self.project = self.project_from_dict(json.loads(session_json))
        except Exception:
            self.project = ProjectModel(style=StyleModel.preset('Light Engineering'))


def _plot_plot_detected_cylinders(self) -> list[str]:
    cfg = self.config_data if isinstance(self.config_data, dict) else {}
    out: list[str] = []
    if 'user_cylinders' in cfg:
        for cyl in cfg.get('user_cylinders', []):
            if isinstance(cyl, dict) and cyl.get('name'):
                if cyl.get('enabled', True):
                    out.append(str(cyl.get('name')))
        return out
    preprocessing = dict(cfg.get('preprocessing') or {})
    for vol in list(preprocessing.get('volumes') or []):
        if isinstance(vol, dict) and str(vol.get('type')) == 'cylinder' and vol.get('name'):
            out.append(str(vol.get('name')))
    return out


def _plot_plot_detect_config_info(self) -> dict[str, Any]:
    cfg = self.config_data if isinstance(self.config_data, dict) else {}
    cycle_raw = self._get_nested_value(
        cfg,
        ('preprocessing', 'engine', 'cycle_type'),
        ('engine', 'cycle_type'),
        ('engine', 'cycle'),
        ('cycle_type',),
        ('cycle',),
    )
    gas_mode_raw = None
    preprocessing = dict(cfg.get('preprocessing') or {})
    connections = list(preprocessing.get('connections') or [])
    if any(isinstance(conn, dict) and str(conn.get('type')) == 'valve' for conn in connections):
        gas_mode_raw = 'valves'
    elif any(isinstance(conn, dict) and str(conn.get('type')) == 'slot' for conn in connections):
        gas_mode_raw = 'slots'
    else:
        gas_mode_raw = self._get_nested_value(cfg, ('gasexchange', 'mode'), ('gasexchange', 'gasexchange_mode'), ('mode',))
    signal_mode_raw = self._get_nested_value(
        cfg,
        ('simulation', 'signal_mode'),
        ('simulation', 'signals', 'mode'),
        ('postprocessing', 'sampling', 'mode'),
        ('signal_mode',),
    )
    preview_source = str(self._get_nested_value(cfg, ('postprocessing', 'csv_path'), ('gasexchange', 'preview_source'), ('preview_source',)) or 'unknown')
    if getattr(self, '_preview_csv_resolution_reason', '') not in {'', 'direct', 'missing'}:
        preview_source = f"{preview_source} -> {getattr(self, '_preview_csv_resolution_reason', '')}"
    cycle_type = self._normalize_cycle_type(cycle_raw)
    gas_mode = self._normalize_gasexchange_mode(gas_mode_raw)
    signal_mode = self._normalize_signal_mode(signal_mode_raw or 'postprocessed_dataframe_columns')
    cylinders = self.detected_cylinders()
    active_cylinder = str(cylinders[0] if cylinders else self.project.selected_cylinder)
    validation = {
        'config_loaded': bool(cfg),
        'signals_loaded': bool(self.catalog.raw),
        'preview_csv_loaded': bool(self.preview_csv.path),
        'preview_csv_error': self.preview_csv.error,
        'signals_error': self.catalog.error,
        'signals_path_valid': True,
    }
    return {
        'cycle_type': cycle_type,
        'gasexchange_mode': gas_mode,
        'signal_mode': signal_mode,
        'preview_source': preview_source,
        'active_cylinder': active_cylinder,
        'cylinders': cylinders,
        'validation': validation,
    }


def _plot_plot_derived_alias_candidates(self, signal: str) -> list[str]:
    resolved = self.resolve(signal)
    mapping = {
        'theta_deg': ['cylinder_theta_deg', resolved.replace('theta_deg', 'cylinder_theta_deg')],
        'theta_local_deg': ['cylinder_theta_deg'],
        'theta_deg_cycle': ['cylinder_theta_deg'],
        'p_cyl_pa': ['cylinder_p_Pa', 'p_cyl_pa'],
        'p_cyl_bar': ['cylinder_p_Pa', 'p_cyl_pa'],
        'V_m3': ['cylinder_V_m3', 'V_m3'],
        'V_cm3': ['cylinder_V_m3', 'V_m3'],
        'T_K': ['cylinder_T_K'],
        'm_kg': ['cylinder_m_kg'],
        'A_in_mm2': ['intake_valve_A_eff_forward_m2', 'transfer_slot_A_eff_forward_m2'],
        'A_ex_mm2': ['exhaust_valve_A_eff_forward_m2', 'exhaust_slot_A_eff_forward_m2'],
    }
    out = list(mapping.get(signal, []))
    out.extend([
        resolved,
        resolved.replace('p_cyl_pa', 'cylinder_p_Pa'),
        resolved.replace('theta_deg', 'cylinder_theta_deg'),
        resolved.replace('V_m3', 'cylinder_V_m3'),
    ])
    return [candidate for candidate in out if candidate]


def _plot_plot_ensure_minimum_project(self) -> None:
    if not self.project.figures:
        self.project.figures = [FigureModel()]
    default_x = _plot_default_x_signal(self)
    default_y = _plot_default_y_signal(self)
    for fig in self.project.figures:
        if not fig.subplots:
            fig.subplots = [SubplotModel(x_signal=default_x)]
        for subplot in fig.subplots:
            if not subplot.y_axes:
                subplot.y_axes = [AxisModel(title='Y', side='left', color='#1f77b4')]
            if not subplot.x_signal:
                subplot.x_signal = default_x
            if not subplot.series:
                axis_id = subplot.y_axes[0].id
                subplot.series = [SeriesModel(signal_key=default_y, label=default_y, axis_id=axis_id, color='#1f77b4')]
            for ser in subplot.series:
                if not ser.axis_id and subplot.y_axes:
                    ser.axis_id = subplot.y_axes[0].id
        if not self.project.style:
            self.project.style = StyleModel.preset('Light Engineering')


def _plot_plot_add_series(self) -> None:
    self.add_series_from_signal(_plot_default_y_signal(self))


def _plot_plot_add_figure(self) -> None:
    fig = FigureModel(title=f'Figure {len(self.project.figures) + 1}')
    fig.subplots[0].x_signal = _plot_default_x_signal(self)
    axis_id = fig.subplots[0].y_axes[0].id
    default_y = _plot_default_y_signal(self)
    fig.subplots[0].series = [SeriesModel(signal_key=default_y, label=default_y, axis_id=axis_id, color='#1f77b4')]
    self.project.figures.append(fig)
    self.refresh_all()
    self.figure_list.setCurrentRow(len(self.project.figures) - 1)
    self.set_dirty('Figure hinzugefügt')


def _plot_plot_add_subplot(self) -> None:
    fig = self.current_figure()
    if fig is None:
        return
    sp = SubplotModel(title=f'Subplot {len(fig.subplots) + 1}', x_signal=_plot_default_x_signal(self))
    axis_id = sp.y_axes[0].id
    default_y = _plot_default_y_signal(self)
    sp.series = [SeriesModel(signal_key=default_y, label=default_y, axis_id=axis_id, color='#1f77b4')]
    fig.subplots.append(sp)
    self.refresh_all()
    self.subplot_list.setCurrentRow(len(fig.subplots) - 1)
    self.set_dirty('Subplot hinzugefügt')


def _plot_plot_create_auto_timing_plot(self, plot_type: str) -> None:
    fig = self.current_figure()
    if fig is None:
        return
    sp = SubplotModel(
        title='Timing' if plot_type == 'timing_cartesian' else 'Timing Polar',
        plot_type=plot_type,
        x_signal=_plot_default_x_signal(self),
        x_title='Theta',
        x_unit_preset='deg',
        x_scale_factor=1.0,
        x_offset=0.0,
        x_limit_mode='data',
        x_min=0.0,
        x_max=720.0,
        y_axes=[AxisModel(title='Opening', side='left', color='#1f77b4')],
        series=[],
        legend_visible=True,
        legend_position='best',
        show_grid=True,
    )
    fig.subplots.append(sp)
    self.refresh_all()
    self.subplot_list.setCurrentRow(len(fig.subplots) - 1)
    self.set_dirty('Auto-Timing-Plot erstellt')


_ORIG_BUILD_ACTIONS = PlotStyleEditor._build_actions
_ORIG_BUILD_MENUS = PlotStyleEditor._build_menus
_ORIG_BUILD_TOOLBAR = PlotStyleEditor._build_toolbar
_ORIG_BUILD_SIGNALS_PANEL = PlotStyleEditor._build_signals_panel
_ORIG_UPDATE_STATUSBAR = PlotStyleEditor.update_statusbar



PlotStyleEditor._build_actions = _plot_build_actions_with_uniform_toggle
PlotStyleEditor._build_menus = _plot_build_menus_with_uniform_toggle
PlotStyleEditor._build_toolbar = _plot_build_toolbar_with_uniform_toggle
PlotStyleEditor._build_signals_panel = _plot_build_signals_panel_with_uniform_toggle
PlotStyleEditor.update_statusbar = _plot_update_statusbar_with_uniform_mode
PlotStyleEditor._validate_signal_catalog_path = _plot_plot_validate_signal_catalog_path
PlotStyleEditor.load_config_from_path = _plot_plot_load_config_from_path
PlotStyleEditor.load_signals_from_path = _plot_plot_load_signals_from_path
PlotStyleEditor.load_preview_csv_from_path = _plot_plot_load_preview_csv_from_path
PlotStyleEditor._auto_open_defaults = _plot_plot_auto_open_defaults
PlotStyleEditor.detected_cylinders = _plot_plot_detected_cylinders
PlotStyleEditor.detect_config_info = _plot_plot_detect_config_info
PlotStyleEditor._ensure_minimum_project = _plot_plot_ensure_minimum_project
PlotStyleEditor.add_series = _plot_plot_add_series
PlotStyleEditor.add_figure = _plot_plot_add_figure
PlotStyleEditor.add_subplot = _plot_plot_add_subplot
PlotStyleEditor.create_auto_timing_plot = _plot_plot_create_auto_timing_plot
SignalCatalog.derived_alias_candidates = _plot_plot_derived_alias_candidates


def _plot_build_actions_with_layout_controls(self) -> None:
    _ORIG_BUILD_ACTIONS(self)
    self.action_layout_save = QAction("Layout speichern", self)
    self.action_layout_save.triggered.connect(self.save_window_layout)
    self.action_layout_reset = QAction("Layout zurücksetzen", self)
    self.action_layout_reset.triggered.connect(self.reset_window_layout)


def _plot_build_menus_with_layout_controls(self) -> None:
    _ORIG_BUILD_MENUS(self)
    self.layout_menu = self.menuBar().addMenu("Layout")
    self.layout_menu.addAction(self.action_layout_save)
    self.layout_menu.addAction(self.action_layout_reset)


def _plot_build_toolbar_with_layout_controls(self) -> None:
    _ORIG_BUILD_TOOLBAR(self)
    for toolbar in self.findChildren(QToolBar):
        if toolbar.objectName() == 'main_toolbar':
            toolbar.addSeparator()
            toolbar.addAction(self.action_layout_save)
            toolbar.addAction(self.action_layout_reset)
            break


def _plot_apply_default_layout(self) -> None:
    for dock in getattr(self, 'all_docks', []):
        self.removeDockWidget(dock)
    self.addDockWidget(Qt.LeftDockWidgetArea, self.project_dock)
    self.splitDockWidget(self.project_dock, self.signals_dock, Qt.Vertical)
    self.addDockWidget(Qt.RightDockWidgetArea, self.preview_dock)
    self.addDockWidget(Qt.BottomDockWidgetArea, self.inspector_dock)
    self.splitDockWidget(self.inspector_dock, self.json_dock, Qt.Horizontal)
    self.resizeDocks([self.project_dock, self.signals_dock], [400, 550], Qt.Vertical)
    self.resizeDocks([self.inspector_dock, self.json_dock], [940, 620], Qt.Horizontal)


def _plot_restore_window_state_with_default_layout(self) -> None:
    geometry = self.settings.value('window/geometry')
    state = self.settings.value('window/state')
    restored = False
    if geometry:
        restored = bool(self.restoreGeometry(geometry))
    if state:
        restored = bool(self.restoreState(state)) or restored
    if not restored:
        self._apply_default_layout()


def _plot_save_window_layout(self) -> None:
    self.settings.setValue('window/geometry', self.saveGeometry())
    self.settings.setValue('window/state', self.saveState())
    self.settings.sync()
    self.statusBar().showMessage('Layout gespeichert', 2500)


def _plot_reset_window_layout(self) -> None:
    self.settings.remove('window/geometry')
    self.settings.remove('window/state')
    self._apply_default_layout()
    self.statusBar().showMessage('Layout zurückgesetzt', 2500)


def _plot_editor_init_with_shell(self, *args, **kwargs) -> None:
    _ORIG_PLOT_INIT(self, *args, **kwargs)
    self.setDockOptions(
        QMainWindow.AllowNestedDocks
        | QMainWindow.AllowTabbedDocks
        | QMainWindow.GroupedDragging
        | QMainWindow.AnimatedDocks
    )
    self.update_statusbar()
    self.statusBar().showMessage('Bereit', 2500)


_ORIG_PLOT_INIT = PlotStyleEditor.__init__
PlotStyleEditor.__init__ = _plot_editor_init_with_shell
PlotStyleEditor._build_actions = _plot_build_actions_with_layout_controls
PlotStyleEditor._build_menus = _plot_build_menus_with_layout_controls
PlotStyleEditor._build_toolbar = _plot_build_toolbar_with_layout_controls
PlotStyleEditor._apply_default_layout = _plot_apply_default_layout
PlotStyleEditor._restore_window_state = _plot_restore_window_state_with_default_layout
PlotStyleEditor.save_window_layout = _plot_save_window_layout
PlotStyleEditor.reset_window_layout = _plot_reset_window_layout


def main() -> int:
    app = QApplication.instance()
    owns_app = app is None
    if owns_app:
        app = QApplication(sys.argv)
    assert app is not None
    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)
    win = PlotStyleEditor()
    show_foreground(win)
    win.raise_()
    win.activateWindow()
    if owns_app:
        return app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
