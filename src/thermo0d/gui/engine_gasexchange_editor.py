from __future__ import annotations

import argparse
import copy
import json
import yaml
import math
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

from thermo0d.config.initial_state_sync import sync_initial_states_inplace
from thermo0d.config_versioning import (
    build_upgrade_message,
    config_schema_version_from_document,
    current_versioning_dict,
    migrate_config_file_in_place,
    requires_version_upgrade,
    stamp_current_versioning,
)
from thermo0d.version import CURRENT_CONFIG_SCHEMA_VERSION
from thermo0d.input.table_loading import load_numeric_table

from thermo0d.gui.dialogs import ask_question, exec_dialog, get_color, get_open_file_name, get_save_file_name, show_critical, show_foreground

from PySide6.QtCore import QEvent, QObject, QPoint, QRect, QRunnable, QSettings, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont, QFontDatabase, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFontComboBox,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStatusBar,
    QStyleFactory,
    QTabWidget,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

APP_ORG = "OpenAI"
APP_NAME = "Thermo0D EngineGasExchangeEditor"

DEFAULT_INTAKE_COLOR = "#2f6df6"
DEFAULT_EXHAUST_COLOR = "#e53935"
DEFAULT_AUX_COLOR = "#9a9a9a"
DEFAULT_BG_COLOR = "#ffffff"
DEFAULT_TEXT_COLOR = "#202020"
DEFAULT_GRID_COLOR = "#d8d8d8"
DEFAULT_FRAME_COLOR = "#666666"
DEFAULT_JSON_BG = "#101216"
DEFAULT_JSON_TEXT = "#e7edf5"
DEFAULT_SECTION_METAL = "#c9cdd4"
DEFAULT_COVER_COLOR = "#9098a4"

AREA_MODE = "effective_area"
LIFT_MODE = "valve_lift"
HEIGHT_MODE = "slot_height"

RIGHT_AXIS_PISTON_MODE = "piston_travel_ut"
RIGHT_AXIS_VOLUME_MODE = "cylinder_volume"

DISPLAY_MODE_LABELS = {
    AREA_MODE: "Effektive Öffnungsfläche",
    LIFT_MODE: "Ventilhub",
    HEIGHT_MODE: "Slot-Höhe",
}

RIGHT_AXIS_MODE_LABELS = {
    RIGHT_AXIS_PISTON_MODE: "Kolbenweg ab UT",
    RIGHT_AXIS_VOLUME_MODE: "Volumen",
}

MODE_CHOICES = ["valves", "ports", "slots"]
CYCLE_CHOICES = ["2T", "4T"]
ROOF_CHOICES = ["none", "linear", "cos", "factor", "angle"]
GRID_STYLE_CHOICES = ["solid", "dash", "dot"]
LEGEND_POSITIONS = ["top_left", "top_right", "bottom_left", "bottom_right"]
ALIGN_CHOICES = ["left", "center", "right"]
WALL_HEAT_MODEL_CHOICES = ["none", "woschni"]
WOSCHNI_VARIANT_CHOICES = ["legacy", "promo", "classic", "swirl", "gt", "huber"]
WOSCHNI_DP_MODE_CHOICES = ["off", "instant", "motored"]
WOSCHNI_REF_MODE_CHOICES = ["none", "pre_combustion_latch", "cycle_start_latch"]
WOSCHNI_PHASE_MODE_CHOICES = ["legacy", "promo", "classic", "gt"]

FORM_LABEL_MIN_WIDTH = 152
FORM_UNIT_MIN_WIDTH = 54
FORM_EDITOR_MIN_WIDTH = 160
FORM_FILE_BADGE_MIN_WIDTH = 180


@dataclass
class PreviewStyleConfig:
    font_family: str = "DejaVu Sans"
    font_size: int = 10
    text_color: str = DEFAULT_TEXT_COLOR
    background_color: str = DEFAULT_BG_COLOR
    grid_visible: bool = True
    grid_color: str = DEFAULT_GRID_COLOR
    grid_style: str = "solid"
    legend_position: str = "top_left"
    title_alignment: str = "left"
    axis_title_alignment: str = "center"
    timing_title: str = ""
    section_title: str = ""
    x_axis_title: str = ""
    left_axis_title: str = ""
    right_axis_title: str = ""
    y_axis_min: float = 0.0
    y_axis_max: float = 1.0
    y_axis_step: float = 0.2
    x_grid_step_deg: float = 60.0
    x_major_grid_step_deg: float = 180.0
    intake_color: str = DEFAULT_INTAKE_COLOR
    exhaust_color: str = DEFAULT_EXHAUST_COLOR
    aux_color: str = DEFAULT_AUX_COLOR
    frame_color: str = DEFAULT_FRAME_COLOR
    json_font_family: str = "DejaVu Sans Mono"
    json_font_size: int = 10
    json_background_color: str = DEFAULT_JSON_BG
    json_text_color: str = DEFAULT_JSON_TEXT
    section_metal_color: str = DEFAULT_SECTION_METAL
    section_cover_color: str = DEFAULT_COVER_COLOR

    @classmethod
    def defaults(cls) -> "PreviewStyleConfig":
        return cls()

    @classmethod
    def from_settings(cls, settings: QSettings) -> "PreviewStyleConfig":
        raw = settings.value("preview/style_json", "")
        if not raw:
            return cls.defaults()
        try:
            data = json.loads(str(raw))
        except Exception:
            return cls.defaults()
        base = asdict(cls.defaults())
        for key in list(base.keys()):
            if key in data:
                base[key] = data[key]
        style = cls(**base)
        if style.grid_style not in GRID_STYLE_CHOICES:
            style.grid_style = "solid"
        if style.legend_position not in LEGEND_POSITIONS:
            style.legend_position = "top_left"
        if style.title_alignment not in ALIGN_CHOICES:
            style.title_alignment = "left"
        if style.axis_title_alignment not in ALIGN_CHOICES:
            style.axis_title_alignment = "center"
        try:
            style.y_axis_min = float(style.y_axis_min)
        except Exception:
            style.y_axis_min = 0.0
        try:
            style.y_axis_max = float(style.y_axis_max)
        except Exception:
            style.y_axis_max = 1.0
        try:
            style.y_axis_step = float(style.y_axis_step)
        except Exception:
            style.y_axis_step = 0.2
        try:
            style.x_grid_step_deg = float(style.x_grid_step_deg)
        except Exception:
            style.x_grid_step_deg = 60.0
        try:
            style.x_major_grid_step_deg = float(style.x_major_grid_step_deg)
        except Exception:
            style.x_major_grid_step_deg = 180.0
        style.y_axis_max = max(style.y_axis_max, style.y_axis_min + 1e-6)
        style.y_axis_step = max(style.y_axis_step, 1e-6)
        style.x_grid_step_deg = max(style.x_grid_step_deg, 1.0)
        style.x_major_grid_step_deg = max(style.x_major_grid_step_deg, style.x_grid_step_deg)
        return style

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


def deep_get(data: dict[str, Any], path: str, default: Any = None) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def deep_set(data: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = data
    for part in parts[:-1]:
        node = cur.get(part)
        if not isinstance(node, dict):
            node = {}
            cur[part] = node
        cur = node
    cur[parts[-1]] = value


def ensure_path(data: dict[str, Any], path: str, default: Any) -> Any:
    value = deep_get(data, path, None)
    if value is None:
        value = copy.deepcopy(default)
        deep_set(data, path, value)
    return value


def merge_dicts(base: dict[str, Any], extra: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (extra or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = merge_dicts(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def compact_number(value: float | int | None, digits: int = 12) -> str:
    if value is None:
        return ""
    v = float(value)
    if abs(v) < 1e-15:
        return "0"
    if abs(v) >= 1e7 or (0 < abs(v) < 1e-6):
        return f"{v:.6g}"
    text = f"{v:.{digits}f}".rstrip("0").rstrip(".")
    return "0" if text in {"", "-0", "+0"} else text


def cycle_span_deg(cycle_type: str) -> int:
    return 360 if str(cycle_type).upper() == "2T" else 720


def plot_x_range(cycle_type: str, start_from_zero: bool) -> tuple[float, float]:
    span = float(cycle_span_deg(cycle_type))
    half_span = 0.5 * span
    return (0.0, span) if start_from_zero else (-half_span, half_span)


def normalize_theta(theta_deg: float, cycle_type: str) -> float:
    span = float(cycle_span_deg(cycle_type))
    value = float(theta_deg)
    while value < 0.0:
        value += span
    while value >= span:
        value -= span
    return value


def nice_axis_max(value: float) -> float:
    if value <= 0.0:
        return 1.0
    exponent = math.floor(math.log10(value))
    decade = 10.0 ** exponent
    fraction = value / decade
    for candidate in (1.0, 2.0, 2.5, 4.0, 5.0, 8.0, 10.0):
        if fraction <= candidate:
            return candidate * decade
    return 10.0 * decade


def nice_ticks(ymax: float, count: int = 4) -> list[float]:
    if ymax <= 0.0:
        return [0.0, 1.0]
    return [ymax * i / count for i in range(count + 1)]


def axis_ticks(ymin: float, ymax: float, step: float) -> list[float]:
    step = max(float(step), 1e-12)
    if ymax <= ymin:
        return [ymin, ymax]
    start = math.ceil(ymin / step) * step
    values = [float(ymin)]
    x = start
    guard = 0
    while x < ymax - 1e-12 and guard < 10000:
        if x > ymin + 1e-12:
            values.append(float(x))
        x += step
        guard += 1
    if ymax > ymin + 1e-12:
        values.append(float(ymax))
    out: list[float] = []
    for value in values:
        if not out or abs(value - out[-1]) > 1e-9:
            out.append(value)
    return out


def pen_style(name: str) -> Qt.PenStyle:
    return {
        "solid": Qt.SolidLine,
        "dash": Qt.DashLine,
        "dot": Qt.DotLine,
    }.get(name, Qt.SolidLine)


def elide_path_middle(text: str, limit: int = 56) -> str:
    if len(text) <= limit:
        return text
    keep = max(8, (limit - 3) // 2)
    return f"{text[:keep]}...{text[-keep:]}"


def piston_distance_from_ut(stroke_m: float, conrod_m: float, crank_deg: float) -> float:
    r = max(stroke_m * 0.5, 1e-12)
    l = max(conrod_m, r + 1e-9)
    theta = math.radians(crank_deg)
    y_tdc = r + l
    y = r * math.cos(theta) + math.sqrt(max(l * l - (r * math.sin(theta)) ** 2, 0.0))
    distance_from_tdc = y_tdc - y
    return stroke_m - distance_from_tdc


def cylinder_volume_m3(
    bore_m: float,
    stroke_m: float,
    conrod_m: float,
    compression_ratio: float,
    crank_deg: float,
) -> float:
    area = math.pi * bore_m * bore_m / 4.0
    swept = area * stroke_m
    cr = max(float(compression_ratio), 1.01)
    clearance = swept / (cr - 1.0)
    piston_from_ut = piston_distance_from_ut(stroke_m, conrod_m, crank_deg)
    piston_from_tdc = stroke_m - piston_from_ut
    return clearance + area * piston_from_tdc


def valve_lift_profile(theta_deg: float, center_deg: float, span_deg: float, max_lift_m: float, cycle_type: str) -> float:
    span_profile = max(float(span_deg), 1e-9)
    span = float(cycle_span_deg(cycle_type))
    half = span_profile * 0.5
    delta = theta_deg - float(center_deg)
    while delta > span * 0.5:
        delta -= span
    while delta < -span * 0.5:
        delta += span
    if abs(delta) > half:
        return 0.0
    phase = (delta + half) / span
    return max_lift_m * 0.5 * (1.0 - math.cos(2.0 * math.pi * phase))


def parse_numeric_text_preview(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {
        "title": path.name,
        "path": str(path),
        "x": [],
        "y": [],
        "x_label": "x",
        "y_label": "y",
        "message": "",
        "error": "",
        "stats": {},
    }
    if not path.exists():
        result["error"] = "Datei nicht gefunden."
        return result
    try:
        suffix = path.suffix.lower()
        if suffix == ".json":
            with path.open("r", encoding="utf-8", errors="replace") as handle:
                data = json.load(handle)
            if isinstance(data, list):
                rows = data
            else:
                rows = []
                if isinstance(data, dict):
                    for value in data.values():
                        if isinstance(value, list):
                            rows = value
                            break
            x_vals: list[float] = []
            y_vals: list[float] = []
            if rows and all(isinstance(row, dict) for row in rows):
                numeric_keys: list[str] = []
                first = rows[0]
                for key in first.keys():
                    if all(isinstance(r.get(key), (int, float)) for r in rows[: min(len(rows), 32)] if isinstance(r, dict)):
                        numeric_keys.append(key)
                if len(numeric_keys) >= 2:
                    result["x_label"], result["y_label"] = numeric_keys[:2]
                    for row in rows:
                        x_vals.append(float(row[numeric_keys[0]]))
                        y_vals.append(float(row[numeric_keys[1]]))
                elif len(numeric_keys) == 1:
                    result["y_label"] = numeric_keys[0]
                    for idx, row in enumerate(rows):
                        x_vals.append(float(idx))
                        y_vals.append(float(row[numeric_keys[0]]))
            elif rows and all(isinstance(row, (list, tuple)) for row in rows):
                for idx, row in enumerate(rows):
                    nums = [float(v) for v in row if isinstance(v, (int, float))]
                    if len(nums) >= 2:
                        x_vals.append(nums[0])
                        y_vals.append(nums[1])
                    elif len(nums) == 1:
                        x_vals.append(float(idx))
                        y_vals.append(nums[0])
            result["x"] = x_vals[:5000]
            result["y"] = y_vals[:5000]
            if result["y"]:
                result["stats"] = compute_preview_stats(result["x"], result["y"], path)
            else:
                result["message"] = "Keine numerischen Daten erkannt."
            return result

        with path.open("r", encoding="utf-8", errors="replace") as handle:
            sample = handle.read(200000)
        pattern = re.compile(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?")
        x_vals: list[float] = []
        y_vals: list[float] = []
        for idx, line in enumerate(sample.splitlines()):
            stripped = line.strip()
            if not stripped or stripped.startswith(("#", ";", "//")):
                continue
            nums = [float(token) for token in pattern.findall(stripped)]
            if len(nums) >= 2:
                x_vals.append(nums[0])
                y_vals.append(nums[1])
            elif len(nums) == 1:
                x_vals.append(float(len(x_vals)))
                y_vals.append(nums[0])
            if len(y_vals) >= 5000:
                break
        result["x"] = x_vals
        result["y"] = y_vals
        if y_vals:
            result["stats"] = compute_preview_stats(result["x"], result["y"], path)
        else:
            result["message"] = "Keine numerischen Spalten erkannt."
    except Exception as exc:
        result["error"] = str(exc)
    return result


class CompactDoubleSpinBox(QDoubleSpinBox):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setDecimals(12)
        self.setKeyboardTracking(False)
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

    def textFromValue(self, value: float) -> str:
        return compact_number(value, digits=12)

    def valueFromText(self, text: str) -> float:
        cleaned = text.strip().replace(",", ".")
        if not cleaned:
            return 0.0
        try:
            return float(cleaned)
        except ValueError:
            return self.value()


class ResponsiveFormBox(QGroupBox):
    def __init__(self, title: str) -> None:
        super().__init__(title)
        self._items: list[QWidget] = []
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(10, 10, 10, 10)
        self._grid.setHorizontalSpacing(14)
        self._grid.setVerticalSpacing(8)

    def addField(self, widget: QWidget) -> None:
        widget.setParent(self)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._items.append(widget)
        self.relayout()

    def relayout(self) -> None:
        while self._grid.count():
            item = self._grid.takeAt(0)
            child = item.widget()
            if child is not None:
                self._grid.removeWidget(child)
        visible = [widget for widget in self._items if not widget.isHidden()]
        width = max(self.width(), self.sizeHint().width())
        columns = 2 if width >= 920 else 1
        for index, widget in enumerate(visible):
            row = index // columns
            column = index % columns
            self._grid.addWidget(widget, row, column)
            self._grid.setColumnStretch(column, 1)
        self._grid.setRowStretch(max(0, len(visible) // columns) + 1, 1)

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self.relayout()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.relayout()


class ColorButton(QPushButton):
    colorChanged = Signal(str)

    def __init__(self, color: str, text: str = "") -> None:
        super().__init__(text or color)
        self._color = color
        self.clicked.connect(self.pick_color)
        self.setMinimumWidth(96)
        self.refresh_style()

    def color(self) -> str:
        return self._color

    def setColor(self, color: str) -> None:
        if color and QColor(color).isValid() and color != self._color:
            self._color = color
            self.refresh_style()
            self.colorChanged.emit(color)
        else:
            self.refresh_style()

    def refresh_style(self) -> None:
        self.setText(self._color)
        self.setStyleSheet(
            "QPushButton {"
            f"background-color: {self._color};"
            f"color: {'#000000' if QColor(self._color).lightness() > 128 else '#ffffff'};"
            "border: 1px solid #888;"
            "padding: 4px 8px;"
            "}"
        )

    def pick_color(self) -> None:
        color = get_color(QColor(self._color), self, "Farbe auswählen")
        if color.isValid():
            self.setColor(color.name())


def compute_preview_stats(x_vals: list[float], y_vals: list[float], path: Path | None = None) -> dict[str, Any]:
    if not y_vals:
        return {}
    stats: dict[str, Any] = {
        "y_max": max(float(v) for v in y_vals),
        "y_min": min(float(v) for v in y_vals),
    }
    if x_vals:
        stats["x_min"] = min(float(v) for v in x_vals)
        stats["x_max"] = max(float(v) for v in x_vals)
    active = [idx for idx, value in enumerate(y_vals) if abs(float(value)) > 1.0e-12]
    if path is not None:
        name = path.name.lower()
        stats["is_lift_profile"] = ("lift" in name) or ("hub" in name)
    return stats

class FilePreviewTaskSignals(QObject):
    loaded = Signal(int, str, dict)


class FilePreviewTask(QRunnable):
    def __init__(self, token: int, path: str) -> None:
        super().__init__()
        self.token = token
        self.path = path
        self.signals = FilePreviewTaskSignals()

    def run(self) -> None:
        result = parse_numeric_text_preview(Path(self.path))
        self.signals.loaded.emit(self.token, self.path, result)


class FilePreviewPlotWidget(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.result: dict[str, Any] = {"x": [], "y": [], "message": "", "error": ""}
        self.style = PreviewStyleConfig.defaults()
        self.setMinimumSize(320, 180)

    def setPreview(self, result: dict[str, Any], style: PreviewStyleConfig) -> None:
        self.result = result
        self.style = style
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(self.style.background_color))
        painter.setPen(QPen(QColor(self.style.frame_color), 1.0))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))

        font = QFont(self.style.font_family, max(7, self.style.font_size - 1))
        painter.setFont(font)
        painter.setPen(QPen(QColor(self.style.text_color), 1.0))

        plot = self.rect().adjusted(42, 20, -18, -28)
        x_vals = self.result.get("x") or []
        y_vals = self.result.get("y") or []

        if self.result.get("error"):
            painter.drawText(plot, Qt.AlignCenter | Qt.TextWordWrap, self.result["error"])
            return
        if not y_vals:
            message = self.result.get("message") or "Keine darstellbaren Daten."
            painter.drawText(plot, Qt.AlignCenter | Qt.TextWordWrap, message)
            return

        x_min = min(x_vals) if x_vals else 0.0
        x_max = max(x_vals) if x_vals else float(len(y_vals) - 1)
        if abs(x_max - x_min) < 1e-12:
            x_max = x_min + 1.0
        y_min = min(y_vals)
        y_max = max(y_vals)
        if abs(y_max - y_min) < 1e-12:
            y_max = y_min + 1.0

        pad = (y_max - y_min) * 0.06
        y_min -= pad
        y_max += pad

        if self.style.grid_visible:
            painter.setPen(QPen(QColor(self.style.grid_color), 1.0, pen_style(self.style.grid_style)))
            for i in range(5):
                y = plot.bottom() - i * plot.height() / 4.0
                painter.drawLine(plot.left(), int(y), plot.right(), int(y))

        painter.setPen(QPen(QColor(self.style.frame_color), 1.0))
        painter.drawRect(plot)

        def x_to_px(value: float) -> float:
            return plot.left() + (value - x_min) / (x_max - x_min) * plot.width()

        def y_to_px(value: float) -> float:
            return plot.bottom() - (value - y_min) / (y_max - y_min) * plot.height()

        painter.setPen(QPen(QColor(self.style.aux_color), 1.7))
        last: tuple[float, float] | None = None
        for x_value, y_value in zip(x_vals if x_vals else range(len(y_vals)), y_vals):
            point = (x_to_px(float(x_value)), y_to_px(float(y_value)))
            if last is not None:
                painter.drawLine(int(last[0]), int(last[1]), int(point[0]), int(point[1]))
            last = point

        painter.setPen(QPen(QColor(self.style.text_color), 1.0))
        painter.drawText(6, 14, self.result.get("title", "Dateivorschau"))
        stats = dict(self.result.get("stats") or {})
        if "y_max" in stats:
            y_max_text = f"y_max={compact_number(stats['y_max'], digits=6)}"
            painter.drawText(plot.right() - painter.fontMetrics().horizontalAdvance(y_max_text), 14, y_max_text)
        painter.drawText(plot.left(), self.height() - 8, self.result.get("x_label", "x"))
        painter.drawText(8, plot.top() + 12, self.result.get("y_label", "y"))


class FilePreviewPopup(QWidget):
    def __init__(self) -> None:
        super().__init__(None, Qt.ToolTip)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)
        self.title_label = QLabel()
        self.title_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.path_label = QLabel()
        self.path_label.setWordWrap(True)
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.info_label = QLabel()
        self.info_label.setWordWrap(True)
        self.info_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.plot = FilePreviewPlotWidget()
        layout.addWidget(self.title_label)
        layout.addWidget(self.path_label)
        layout.addWidget(self.info_label)
        layout.addWidget(self.plot)
        self.resize(420, 300)

    def apply_preview(self, result: dict[str, Any], style: PreviewStyleConfig) -> None:
        palette = self.palette()
        palette.setColor(QPalette.Window, QColor(style.background_color))
        palette.setColor(QPalette.WindowText, QColor(style.text_color))
        self.setPalette(palette)
        self.setAutoFillBackground(True)
        label_font = QFont(style.font_family, style.font_size)
        self.title_label.setFont(label_font)
        self.path_label.setFont(QFont(style.font_family, max(7, style.font_size - 1)))
        self.info_label.setFont(QFont(style.font_family, max(7, style.font_size - 1)))
        label_style = f"color: {style.text_color};"
        self.title_label.setStyleSheet(label_style)
        self.path_label.setStyleSheet(label_style)
        self.info_label.setStyleSheet(label_style)
        self.title_label.setText(result.get("title", "Dateivorschau"))
        self.path_label.setText(elide_path_middle(result.get("path", ""), 78))
        self.path_label.setToolTip(result.get("path", ""))
        stats = dict(result.get("stats") or {})
        info_parts: list[str] = []
        if "y_max" in stats:
            info_parts.append(f"y_max={compact_number(stats['y_max'], digits=6)}")
        self.info_label.setText(" | ".join(info_parts))
        self.info_label.setVisible(bool(info_parts))
        self.plot.setPreview(result, style)

    def show_near(self, anchor: QWidget) -> None:
        try:
            global_pos = anchor.mapToGlobal(QPoint(anchor.width() + 12, anchor.height() + 4))
        except RuntimeError:
            self.hide()
            return
        except Exception:
            self.hide()
            return
        self.move(global_pos)
        self.show()
        self.raise_()


class BoundField(QWidget):
    valueChanged = Signal(str)

    def __init__(
        self,
        editor: "EngineGasExchangeEditor",
        title: str,
        json_path: str,
        field_type: str = "float",
        *,
        unit_kind: str | None = None,
        minimum: float = -1e12,
        maximum: float = 1e12,
        step: float = 0.001,
        choices: list[str] | None = None,
        read_only: bool = False,
    ) -> None:
        super().__init__()
        self.editor = editor
        self.title = title
        self.json_path = json_path
        self.field_type = field_type
        self.unit_kind = unit_kind
        self.model_minimum = minimum
        self.model_maximum = maximum
        self.model_step = step
        self.read_only = read_only

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.label = QLabel(title)
        self.label.setMinimumWidth(FORM_LABEL_MIN_WIDTH)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(self.label)

        if field_type == "float":
            self.widget: QWidget = CompactDoubleSpinBox()
            self.widget.setMinimumWidth(FORM_EDITOR_MIN_WIDTH)
            self.widget.valueChanged.connect(self._commit)
        elif field_type == "int":
            self.widget = QSpinBox()
            self.widget.setKeyboardTracking(False)
            self.widget.setMinimumWidth(120)
            self.widget.valueChanged.connect(self._commit)
        elif field_type == "choice":
            self.widget = QComboBox()
            self.widget.addItems(choices or [])
            self.widget.setMinimumWidth(FORM_EDITOR_MIN_WIDTH)
            self.widget.currentIndexChanged.connect(self._commit)
        elif field_type == "bool":
            self.widget = QCheckBox()
            self.widget.toggled.connect(self._commit)
        else:
            raise ValueError(f"Unsupported field type: {field_type}")
        self.widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(self.widget, 1)

        self.unit_label = QLabel("")
        self.unit_label.setMinimumWidth(FORM_UNIT_MIN_WIDTH)
        self.unit_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        if field_type in {"float", "int"}:
            layout.addWidget(self.unit_label)
        else:
            self.unit_label.hide()

        if hasattr(self.widget, "setReadOnly"):
            self.widget.setReadOnly(read_only)
        self.update_unit_presentation()
        self.editor.register_bindable(self)

    def _display_factor(self) -> float:
        if self.unit_kind == "length":
            return 1000.0 if self.editor.unit_mode == "eng" else 1.0
        if self.unit_kind == "length_mm_value":
            return 1.0 if self.editor.unit_mode == "eng" else 0.001
        if self.unit_kind == "area":
            return 1.0e4 if self.editor.unit_mode == "eng" else 1.0
        if self.unit_kind == "volume":
            return 1.0e6 if self.editor.unit_mode == "eng" else 1.0
        return 1.0

    def model_to_display(self, value: Any) -> Any:
        if self.field_type == "float":
            return float(value or 0.0) * self._display_factor()
        return value

    def display_to_model(self, value: Any) -> Any:
        if self.field_type == "float":
            return float(value) / self._display_factor()
        if self.field_type == "int":
            return int(value)
        return value

    def update_unit_presentation(self) -> None:
        if self.unit_kind == "length":
            text = "mm" if self.editor.unit_mode == "eng" else "m"
        elif self.unit_kind == "length_mm_value":
            text = "mm" if self.editor.unit_mode == "eng" else "m"
        elif self.unit_kind == "area":
            text = "cm²" if self.editor.unit_mode == "eng" else "m²"
        elif self.unit_kind == "volume":
            text = "cm³" if self.editor.unit_mode == "eng" else "m³"
        elif self.unit_kind == "angle":
            text = "deg"
        elif self.unit_kind == "ratio":
            text = "-"
        elif self.unit_kind == "temperature":
            text = "°C" if self.editor.unit_mode == "eng" else "K"
        else:
            text = ""
        self.unit_label.setText(text)

        if self.field_type == "float":
            widget = self.widget
            assert isinstance(widget, CompactDoubleSpinBox)
            factor = self._display_factor()
            widget.blockSignals(True)
            widget.setRange(self.model_minimum * factor, self.model_maximum * factor)
            widget.setSingleStep(max(abs(self.model_step * factor), 1e-12))
            widget.blockSignals(False)
        elif self.field_type == "int":
            widget = self.widget
            assert isinstance(widget, QSpinBox)
            widget.blockSignals(True)
            widget.setRange(int(self.model_minimum), int(self.model_maximum))
            widget.setSingleStep(max(1, int(abs(self.model_step) or 1)))
            widget.blockSignals(False)

    def refresh_from_model(self) -> None:
        self.update_unit_presentation()
        value = deep_get(self.editor.config_data, self.json_path, None)
        self.blockSignals(True)
        self.widget.blockSignals(True)
        try:
            if self.field_type == "float":
                widget = self.widget
                assert isinstance(widget, CompactDoubleSpinBox)
                widget.setValue(float(self.model_to_display(value or 0.0)))
            elif self.field_type == "int":
                widget = self.widget
                assert isinstance(widget, QSpinBox)
                widget.setValue(int(value or 0))
            elif self.field_type == "choice":
                widget = self.widget
                assert isinstance(widget, QComboBox)
                text = str(value or "")
                index = widget.findText(text)
                if index < 0 and widget.count() > 0:
                    index = 0
                if index >= 0:
                    widget.setCurrentIndex(index)
            elif self.field_type == "bool":
                widget = self.widget
                assert isinstance(widget, QCheckBox)
                widget.setChecked(bool(value))
        finally:
            self.widget.blockSignals(False)
            self.blockSignals(False)

    def _commit(self, *_args: Any) -> None:
        if self.editor.loading_ui:
            return
        if self.field_type == "float":
            widget = self.widget
            assert isinstance(widget, CompactDoubleSpinBox)
            value = self.display_to_model(widget.value())
        elif self.field_type == "int":
            widget = self.widget
            assert isinstance(widget, QSpinBox)
            value = int(widget.value())
        elif self.field_type == "choice":
            widget = self.widget
            assert isinstance(widget, QComboBox)
            value = widget.currentText()
        else:
            widget = self.widget
            assert isinstance(widget, QCheckBox)
            value = widget.isChecked()
        deep_set(self.editor.config_data, self.json_path, value)
        self.valueChanged.emit(self.json_path)
        self.editor.on_data_changed(reason=self.json_path)


class ValveAngleBasisField(QWidget):
    valueChanged = Signal(str)

    def __init__(self, editor: "EngineGasExchangeEditor", title: str, json_path: str) -> None:
        super().__init__()
        self.editor = editor
        self.title = title
        self.json_path = json_path

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.label = QLabel(title)
        self.label.setMinimumWidth(FORM_LABEL_MIN_WIDTH)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(self.label)

        button_host = QWidget()
        button_layout = QHBoxLayout(button_host)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(6)

        self.cam_button = QToolButton()
        self.cam_button.setText("CAM")
        self.cam_button.setCheckable(True)
        self.cam_button.clicked.connect(lambda checked=False: self._commit("cam"))
        button_layout.addWidget(self.cam_button)

        self.crank_button = QToolButton()
        self.crank_button.setText("CRANK")
        self.crank_button.setCheckable(True)
        self.crank_button.clicked.connect(lambda checked=False: self._commit("crank"))
        button_layout.addWidget(self.crank_button)
        button_layout.addStretch(1)

        layout.addWidget(button_host, 1)

        self.info_label = QLabel("")
        self.info_label.setMinimumWidth(FORM_UNIT_MIN_WIDTH + 18)
        self.info_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.info_label)

        self.editor.register_bindable(self)

    def refresh_from_model(self) -> None:
        value = str(deep_get(self.editor.config_data, self.json_path, "cam") or "cam").strip().lower()
        if value not in {"cam", "crank"}:
            value = "cam"
        self.blockSignals(True)
        self.cam_button.blockSignals(True)
        self.crank_button.blockSignals(True)
        try:
            self.cam_button.setChecked(value == "cam")
            self.crank_button.setChecked(value == "crank")
            self.info_label.setText(value.upper())
        finally:
            self.crank_button.blockSignals(False)
            self.cam_button.blockSignals(False)
            self.blockSignals(False)

    def _commit(self, value: str) -> None:
        if self.editor.loading_ui:
            return
        value_norm = str(value or "cam").strip().lower()
        if value_norm not in {"cam", "crank"}:
            value_norm = "cam"
        deep_set(self.editor.config_data, self.json_path, value_norm)
        self.valueChanged.emit(self.json_path)
        self.editor.on_data_changed(reason=self.json_path)


class ValveTimingReferenceField(QWidget):
    valueChanged = Signal(str)

    def __init__(self, editor: "EngineGasExchangeEditor", side: str) -> None:
        super().__init__()
        self.editor = editor
        self.side = side
        self.mode = str(editor.settings.value(f"valve_timing_mode/{side}", "open") or "open").strip().lower()
        if self.mode not in {"open", "close", "center"}:
            self.mode = "open"

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.label = QLabel("Timing-Bezug")
        self.label.setMinimumWidth(FORM_LABEL_MIN_WIDTH)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(self.label)

        button_host = QWidget()
        button_layout = QHBoxLayout(button_host)
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(6)

        self.open_button = QToolButton()
        self.open_button.setText("Öffnen")
        self.open_button.setCheckable(True)
        self.open_button.clicked.connect(lambda checked=False: self._set_mode("open"))
        button_layout.addWidget(self.open_button)

        self.close_button = QToolButton()
        self.close_button.setText("Schließen")
        self.close_button.setCheckable(True)
        self.close_button.clicked.connect(lambda checked=False: self._set_mode("close"))
        button_layout.addWidget(self.close_button)

        self.center_button = QToolButton()
        self.center_button.setText("Center")
        self.center_button.setCheckable(True)
        self.center_button.clicked.connect(lambda checked=False: self._set_mode("center"))
        button_layout.addWidget(self.center_button)
        button_layout.addStretch(1)

        layout.addWidget(button_host, 1)

        self.value_label = QLabel("")
        self.value_label.setMinimumWidth(FORM_UNIT_MIN_WIDTH + 18)
        self.value_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.value_label)

        self.editor.register_bindable(self)

    def refresh_from_model(self) -> None:
        self.blockSignals(True)
        self.open_button.blockSignals(True)
        self.close_button.blockSignals(True)
        self.center_button.blockSignals(True)
        try:
            self.open_button.setChecked(self.mode == "open")
            self.close_button.setChecked(self.mode == "close")
            self.center_button.setChecked(self.mode == "center")
            self.value_label.setText(self.mode.upper())
        finally:
            self.center_button.blockSignals(False)
            self.close_button.blockSignals(False)
            self.open_button.blockSignals(False)
            self.blockSignals(False)

    def _set_mode(self, mode: str) -> None:
        value = str(mode or "open").strip().lower()
        if value not in {"open", "close", "center"}:
            value = "open"
        self.mode = value
        self.editor.settings.setValue(f"valve_timing_mode/{self.side}", value)
        self.editor.settings.sync()
        self.refresh_from_model()
        self.valueChanged.emit(f"gasexchange.valves.{self.side}._timing_reference")
        self.editor.on_data_changed(reason=f"gasexchange.valves.{self.side}._timing_reference")


class ValveTimingValueField(QWidget):
    valueChanged = Signal(str)

    def __init__(self, editor: "EngineGasExchangeEditor", side_editor: "ValveSideEditor") -> None:
        super().__init__()
        self.editor = editor
        self.side_editor = side_editor
        self.side = side_editor.side

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.label = QLabel("Öffnen")
        self.label.setMinimumWidth(FORM_LABEL_MIN_WIDTH)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        layout.addWidget(self.label)

        self.widget = CompactDoubleSpinBox()
        self.widget.setMinimumWidth(FORM_EDITOR_MIN_WIDTH)
        self.widget.setRange(-5000.0, 5000.0)
        self.widget.setSingleStep(1.0)
        self.widget.valueChanged.connect(self._commit)
        layout.addWidget(self.widget, 1)

        self.unit_label = QLabel("deg")
        self.unit_label.setMinimumWidth(FORM_UNIT_MIN_WIDTH)
        self.unit_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        layout.addWidget(self.unit_label)

        self.editor.register_bindable(self)

    def refresh_from_model(self) -> None:
        mode = self.side_editor.timing_mode()
        self.label.setText({"open": "Öffnen", "close": "Schließen", "center": "Center"}[mode])
        value = self.editor.valve_timing_value(self.side, mode)
        self.blockSignals(True)
        self.widget.blockSignals(True)
        try:
            self.widget.setValue(float(value))
        finally:
            self.widget.blockSignals(False)
            self.blockSignals(False)

    def _commit(self, *_args: Any) -> None:
        if self.editor.loading_ui:
            return
        mode = self.side_editor.timing_mode()
        model_value = self.widget.value()
        self.editor.set_valve_open_from_display_value(self.side, mode, model_value)
        self.valueChanged.emit(f"gasexchange.valves.{self.side}.open_deg")
        self.editor.on_data_changed(reason=f"gasexchange.valves.{self.side}.open_deg")


class FilePathField(QWidget):
    valueChanged = Signal(str)

    def __init__(self, editor: "EngineGasExchangeEditor", title: str, json_path: str) -> None:
        super().__init__()
        self.editor = editor
        self.title = title
        self.json_path = json_path
        self._last_path = ""
        self._full_path = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(2)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        self.label = QLabel(title)
        self.label.setMinimumWidth(FORM_LABEL_MIN_WIDTH)
        self.label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        row.addWidget(self.label)

        self.edit = QLineEdit()
        self.edit.setMinimumWidth(max(240, FORM_EDITOR_MIN_WIDTH))
        self.edit.setPlaceholderText("Keine Datei ausgewählt")
        self.edit.editingFinished.connect(self._commit)
        row.addWidget(self.edit, 1)

        self.filename_label = QLabel("Keine Datei")
        self.filename_label.setMinimumWidth(min(120, FORM_FILE_BADGE_MIN_WIDTH))
        self.filename_label.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.filename_label.setStyleSheet("color: #60666e;")
        self.filename_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        row.addWidget(self.filename_label)

        self.browse_button = QToolButton()
        self.browse_button.setText("…")
        self.browse_button.clicked.connect(self._browse)
        row.addWidget(self.browse_button)

        outer.addLayout(row)

        path_row = QHBoxLayout()
        path_row.setContentsMargins(0, 0, 0, 0)
        path_row.setSpacing(8)
        spacer = QLabel("")
        spacer.setMinimumWidth(FORM_LABEL_MIN_WIDTH)
        spacer.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        path_row.addWidget(spacer)

        self.path_label = QLabel("Kein Pfad gesetzt")
        self.path_label.setStyleSheet("color: #7b828c;")
        self.path_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.path_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        path_row.addWidget(self.path_label, 1)
        outer.addLayout(path_row)

        for widget in (self.edit, self.filename_label, self.path_label):
            widget.installEventFilter(self)
            widget.setToolTip("")

        self.editor.register_bindable(self)

    def refresh_from_model(self) -> None:
        value = str(deep_get(self.editor.config_data, self.json_path, "") or "")
        self._full_path = value
        self.blockSignals(True)
        self.edit.blockSignals(True)
        try:
            self.edit.setText(self._display_name_from_path(value))
            self._update_filename_label(value)
        finally:
            self.edit.blockSignals(False)
            self.blockSignals(False)
        self._last_path = value

    def _browse(self) -> None:
        base_dir = self.editor.current_path.parent if self.editor.current_path else Path.cwd()
        start_path = Path(self._full_path) if self._full_path else base_dir
        start_dir = str(start_path.parent if start_path.exists() and start_path.is_file() else start_path)
        filename, _ = get_open_file_name(self, "Datei auswählen", start_dir, "Alle Dateien (*.*)")
        if filename:
            self._apply_committed_path(str(Path(filename).resolve()))

    def _display_name_from_path(self, path_text: str) -> str:
        path_text = str(path_text or "").strip()
        if not path_text:
            return ""
        path = Path(path_text)
        return path.name if path.name else path_text

    def _resolve_committed_text(self, raw_text: str) -> str:
        text = str(raw_text or "").strip()
        if not text:
            return ""
        if os.path.isabs(text) or any(sep and sep in text for sep in (os.sep, os.altsep)):
            return str(Path(text))
        current_full = str(self._full_path or self._last_path or "").strip()
        if current_full:
            current_parent = Path(current_full).parent
            if str(current_parent) not in {"", "."}:
                return str(current_parent / text)
        if self.editor.current_path is not None:
            return str(self.editor.current_path.parent / text)
        return text

    def _apply_committed_path(self, value: str) -> None:
        deep_set(self.editor.config_data, self.json_path, value)
        self._full_path = value
        self._update_filename_label(value)
        self.edit.blockSignals(True)
        self.edit.setText(self._display_name_from_path(value))
        self.edit.blockSignals(False)
        if value != self._last_path:
            self.editor.invalidate_file_preview_cache(self._last_path)
            self.editor.invalidate_file_preview_cache(value)
            self._last_path = value
        self.valueChanged.emit(self.json_path)
        self.editor.on_data_changed(reason=self.json_path)

    def _update_filename_label(self, path_text: str) -> None:
        if not path_text:
            self.filename_label.setText("Keine Datei")
            self.path_label.setText("Kein Pfad gesetzt")
            self.edit.setText("")
            for widget in (self.filename_label, self.path_label, self.edit):
                widget.setToolTip("")
            return
        path = Path(path_text)
        filename = path.name if path.name else path_text
        self.filename_label.setText(filename)
        self.path_label.setText(elide_path_middle(path_text, 120))
        self.filename_label.setToolTip(path_text)
        self.path_label.setToolTip(path_text)
        self.edit.setToolTip(path_text)

    def _commit(self, *_args: Any) -> None:
        if self.editor.loading_ui:
            return
        value = self._resolve_committed_text(self.edit.text())
        self._apply_committed_path(value)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        try:
            if obj in (self.edit, self.filename_label, self.path_label):
                event_type = event.type()
                if event_type in (QEvent.Enter, QEvent.MouseMove, QEvent.ToolTip):
                    anchor = obj if isinstance(obj, QWidget) else self
                    path_text = str(self._full_path or self._last_path or "").strip()
                    if path_text:
                        self.editor.request_file_preview(anchor, path_text)
                elif event_type == QEvent.Leave:
                    self.editor.hide_file_preview_later()
        except RuntimeError:
            return False
        except Exception:
            return False
        return False


class EngineEditorPanel(QWidget):
    def __init__(self, editor: "EngineGasExchangeEditor") -> None:
        super().__init__()
        self.editor = editor
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        box = ResponsiveFormBox("Engine")
        self.fields = [
            BoundField(editor, "Cycle type", "engine.cycle_type", "choice", choices=CYCLE_CHOICES),
            BoundField(editor, "Bore", "engine.bore_m", "float", unit_kind="length", minimum=0.001, maximum=5.0, step=0.0005),
            BoundField(editor, "Stroke", "engine.stroke_m", "float", unit_kind="length", minimum=0.001, maximum=5.0, step=0.0005),
            BoundField(editor, "Conrod", "engine.conrod_m", "float", unit_kind="length", minimum=0.001, maximum=5.0, step=0.0005),
            BoundField(editor, "Compression ratio", "engine.compression_ratio", "float", unit_kind="ratio", minimum=1.0, maximum=40.0, step=0.1),
        ]
        for field in self.fields:
            box.addField(field)
        layout.addWidget(box)

        wall_box = ResponsiveFormBox("Wall heat")
        self.wall_model_field = BoundField(editor, "Model", "engine.wall_heat.model", "choice", choices=WALL_HEAT_MODEL_CHOICES)
        self.wall_variant_field = BoundField(editor, "Variant", "engine.wall_heat.variant", "choice", choices=WOSCHNI_VARIANT_CHOICES)
        self.wall_temp_field = BoundField(editor, "Wall temperature", "engine.wall_heat.wall_temperature_K", "float", unit_kind="temperature", minimum=1.0, maximum=4000.0, step=1.0)
        self.wall_area_field = BoundField(editor, "Wall area", "engine.wall_heat.wall_area_m2", "float", unit_kind="area", minimum=0.0, maximum=10.0, step=1.0e-4)
        self.wall_multiplier_field = BoundField(editor, "Multiplier", "engine.wall_heat.multiplier", "float", minimum=0.0, maximum=100.0, step=0.01)
        self.wall_dp_mode_field = BoundField(editor, "Δp mode", "engine.wall_heat.dp_mode", "choice", choices=WOSCHNI_DP_MODE_CHOICES)
        self.wall_ref_mode_field = BoundField(editor, "Reference state", "engine.wall_heat.reference_state_mode", "choice", choices=WOSCHNI_REF_MODE_CHOICES)
        self.wall_phase_mode_field = BoundField(editor, "Phase mode", "engine.wall_heat.phase_mode", "choice", choices=WOSCHNI_PHASE_MODE_CHOICES)
        self.wall_c1_field = BoundField(editor, "c1", "engine.wall_heat.c1", "float", minimum=-1.0e6, maximum=1.0e6, step=0.01)
        self.wall_c2_field = BoundField(editor, "c2", "engine.wall_heat.c2", "float", minimum=-1.0e6, maximum=1.0e6, step=1.0e-5)
        self.wall_c3_field = BoundField(editor, "c3", "engine.wall_heat.c3", "float", minimum=-1.0e6, maximum=1.0e6, step=1.0e-5)
        self.wall_cucm_field = BoundField(editor, "CUCM", "engine.wall_heat.cucm", "float", minimum=-1000.0, maximum=1000.0, step=0.01)
        self.wall_swirl_field = BoundField(editor, "Swirl number", "engine.wall_heat.swirl_number", "float", minimum=-1000.0, maximum=1000.0, step=0.01)
        self.wall_imep_field = BoundField(editor, "IMEP", "engine.wall_heat.imep_bar", "float", minimum=-200.0, maximum=200.0, step=0.01)
        self.wall_fields = [
            self.wall_model_field,
            self.wall_variant_field,
            self.wall_temp_field,
            self.wall_area_field,
            self.wall_multiplier_field,
            self.wall_dp_mode_field,
            self.wall_ref_mode_field,
            self.wall_phase_mode_field,
            self.wall_c1_field,
            self.wall_c2_field,
            self.wall_c3_field,
            self.wall_cucm_field,
            self.wall_swirl_field,
            self.wall_imep_field,
        ]
        for field in self.wall_fields:
            wall_box.addField(field)
        layout.addWidget(wall_box)
        layout.addStretch(1)
        self.editor.register_bindable(self)

    def refresh_from_model(self) -> None:
        model = str(deep_get(self.editor.config_data, "engine.wall_heat.model", "none") or "none").strip().lower()
        variant = str(deep_get(self.editor.config_data, "engine.wall_heat.variant", "legacy") or "legacy").strip().lower()
        is_woschni = model == "woschni"
        for field in self.wall_fields:
            field.setVisible(True)
        self.wall_variant_field.setVisible(is_woschni)
        self.wall_temp_field.setVisible(is_woschni)
        self.wall_area_field.setVisible(is_woschni)
        self.wall_multiplier_field.setVisible(is_woschni)
        self.wall_dp_mode_field.setVisible(is_woschni)
        self.wall_ref_mode_field.setVisible(is_woschni)
        self.wall_phase_mode_field.setVisible(is_woschni)
        legacy = is_woschni and variant == "legacy"
        self.wall_c1_field.setVisible(legacy)
        self.wall_c2_field.setVisible(legacy)
        self.wall_c3_field.setVisible(legacy)
        self.wall_cucm_field.setVisible(is_woschni)
        self.wall_swirl_field.setVisible(is_woschni and variant in {"swirl", "gt", "huber"})
        self.wall_imep_field.setVisible(is_woschni and variant == "huber")


class ValveSideEditor(QWidget):
    def __init__(self, editor: "EngineGasExchangeEditor", side: str, title: str, color: str) -> None:
        super().__init__()
        self.editor = editor
        self.side = side
        self.base_path = f"gasexchange.valves.{side}"
        self.scaling_base_path = f"gasexchange.valves.scaling.{side}"
        self._updating = False

        box = ResponsiveFormBox(title)
        box.setStyleSheet(f"QGroupBox {{ font-weight: 600; color: {color}; }}")

        self.lift_file = FilePathField(editor, "Lift file", f"{self.base_path}.lift_file")
        self.alphak_file = FilePathField(editor, "AlphaK file", f"{self.base_path}.alphak_file")
        self.lift_angle_basis_field = ValveAngleBasisField(editor, "Lift basis", f"{self.base_path}.profile_angle_domain")
        self.cam_to_crank_ratio_field = BoundField(editor, "Cam to crank ratio", "gasexchange.valves.cam_to_crank_ratio", "float", minimum=0.01, maximum=20.0, step=0.01)
        self.effective_lift_threshold_field = BoundField(editor, "Effective lift threshold", "gasexchange.valves.effective_lift_threshold_mm", "float", unit_kind="length_mm_value", minimum=0.0, maximum=50.0, step=0.01)

        count_path = "gasexchange.valves.count_in" if side == "intake" else "gasexchange.valves.count_ex"

        self.count_field = BoundField(editor, "Count", count_path, "int", minimum=0, maximum=16, step=1)
        self.angle_scale_field = BoundField(editor, "Angle scale", f"{self.scaling_base_path}.angle_scale", "float", minimum=0.01, maximum=20.0, step=0.01)
        self.lift_scale_field = BoundField(editor, "Lift scale", f"{self.scaling_base_path}.lift_scale", "float", minimum=0.01, maximum=20.0, step=0.01)
        self.timing_reference_field = ValveTimingReferenceField(editor, side)
        self.timing_value_field = ValveTimingValueField(editor, self)

        self.cam_to_crank_ratio_field.hide()
        for field in (
            self.lift_file,
            self.alphak_file,
            self.lift_angle_basis_field,
            self.effective_lift_threshold_field,
            self.count_field,
            self.angle_scale_field,
            self.lift_scale_field,
            self.timing_reference_field,
            self.timing_value_field,
        ):
            box.addField(field)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(box)

        self.editor.register_bindable(self)

    def timing_mode(self) -> str:
        return self.timing_reference_field.mode

    def refresh_from_model(self) -> None:
        self._sync_from_model_fields_only()

    def _sync_from_model_fields_only(self) -> None:
        if self._updating:
            return
        self._updating = True
        try:
            self.editor.normalize_valve_side(self.side)
            for field in (
                self.lift_file,
                self.alphak_file,
                self.lift_angle_basis_field,
                self.effective_lift_threshold_field,
                self.count_field,
                self.angle_scale_field,
                self.lift_scale_field,
                self.timing_reference_field,
                self.timing_value_field,
            ):
                field.refresh_from_model()
        finally:
            self._updating = False


class ValveEditorTab(QWidget):
    def __init__(self, editor: "EngineGasExchangeEditor") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        self.intake_editor = ValveSideEditor(editor, "intake", "Intake", editor.preview_style.intake_color)
        self.exhaust_editor = ValveSideEditor(editor, "exhaust", "Exhaust", editor.preview_style.exhaust_color)

        layout.addWidget(self.intake_editor)
        layout.addWidget(self.exhaust_editor)
        layout.addStretch(1)


class WindowSideEditor(ResponsiveFormBox):
    def __init__(self, editor: "EngineGasExchangeEditor", title: str, base_path: str, color: str) -> None:
        super().__init__(title)
        self.editor = editor
        self.base_path = base_path
        self.setStyleSheet(f"QGroupBox {{ font-weight: 600; color: {color}; }}")

        self.addField(BoundField(editor, "Width", f"{base_path}.width_m", "float", unit_kind="length", minimum=0.0, maximum=1.0, step=0.0005))
        self.addField(BoundField(editor, "Height", f"{base_path}.height_m", "float", unit_kind="length", minimum=0.0, maximum=1.0, step=0.0005))
        self.addField(BoundField(editor, "Count", f"{base_path}.count", "int", minimum=0, maximum=64, step=1))
        self.addField(BoundField(editor, "Offset from UT", f"{base_path}.offset_from_ut_m", "float", unit_kind="length", minimum=-1.0, maximum=1.0, step=0.0005))
        if ".slots." in base_path:
            self.cd_forward = BoundField(editor, "Forward discharge coefficient", f"{base_path}.forward_discharge_coefficient", "float", minimum=0.0, maximum=10.0, step=0.01)
            self.cd_reverse = BoundField(editor, "Reverse discharge coefficient", f"{base_path}.reverse_discharge_coefficient", "float", minimum=0.0, maximum=10.0, step=0.01)
            self.addField(self.cd_forward)
            self.addField(self.cd_reverse)
        else:
            self.alphak_file = FilePathField(editor, "AlphaK file", f"{base_path}.alphak_file")
            self.addField(self.alphak_file)

        self.roof_type = BoundField(editor, "Roof type", f"{base_path}.roof.type", "choice", choices=ROOF_CHOICES)
        self.roof_type.valueChanged.connect(lambda _p: self._apply_roof_visibility())
        self.addField(self.roof_type)

        self.roof_len = BoundField(editor, "Roof length", f"{base_path}.roof.len_m", "float", unit_kind="length", minimum=0.0, maximum=0.25, step=0.0005)
        self.roof_gamma = BoundField(editor, "Roof gamma", f"{base_path}.roof.gamma", "float", minimum=0.0, maximum=20.0, step=0.1)
        self.roof_angle = BoundField(editor, "Roof angle", f"{base_path}.roof.angle_deg", "float", unit_kind="angle", minimum=-360.0, maximum=360.0, step=1.0)
        self.addField(self.roof_len)
        self.addField(self.roof_gamma)
        self.addField(self.roof_angle)
        self.editor.register_bindable(self)
        self._apply_roof_visibility()

    def refresh_from_model(self) -> None:
        self._apply_roof_visibility()

    def _apply_roof_visibility(self) -> None:
        roof_type = str(deep_get(self.editor.config_data, f"{self.base_path}.roof.type", "none") or "none")
        self.roof_len.setVisible(roof_type in {"linear", "cos", "factor"})
        self.roof_gamma.setVisible(roof_type == "factor")
        self.roof_angle.setVisible(roof_type == "angle")
        self.relayout()


class PortEditorTab(QWidget):
    def __init__(self, editor: "EngineGasExchangeEditor") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        files = ResponsiveFormBox("Ports")
        self.area_file = FilePathField(editor, "Area file", "gasexchange.ports.area_file")
        self.alphak_file = FilePathField(editor, "AlphaK file", "gasexchange.ports.alphak_file")
        files.addField(self.area_file)
        files.addField(self.alphak_file)
        layout.addWidget(files)

        info = QLabel(
            "Die Datei-Felder bleiben fachlich aktiv. Zusätzliche Geometrieparameter dienen der Timing- und Section-Vorschau."
        )
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addWidget(WindowSideEditor(editor, "Intake port geometry", "gasexchange.ports.intake", editor.preview_style.intake_color))
        layout.addWidget(WindowSideEditor(editor, "Exhaust port geometry", "gasexchange.ports.exhaust", editor.preview_style.exhaust_color))
        layout.addStretch(1)


class SlotEditorTab(QWidget):
    def __init__(self, editor: "EngineGasExchangeEditor") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        header = ResponsiveFormBox("Slots")
        self.cd_forward = BoundField(editor, "Shared forward discharge coefficient", "gasexchange.slots.forward_discharge_coefficient", "float", minimum=0.0, maximum=10.0, step=0.01)
        self.cd_reverse = BoundField(editor, "Shared reverse discharge coefficient", "gasexchange.slots.reverse_discharge_coefficient", "float", minimum=0.0, maximum=10.0, step=0.01)
        header.addField(self.cd_forward)
        header.addField(self.cd_reverse)
        layout.addWidget(header)
        layout.addWidget(WindowSideEditor(editor, "Intake slot geometry", "gasexchange.slots.intake", editor.preview_style.intake_color))
        layout.addWidget(WindowSideEditor(editor, "Exhaust slot geometry", "gasexchange.slots.exhaust", editor.preview_style.exhaust_color))
        layout.addStretch(1)


class GasExchangePanel(QWidget):
    def __init__(self, editor: "EngineGasExchangeEditor") -> None:
        super().__init__()
        self.editor = editor
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)

        mode_box = ResponsiveFormBox("Gasexchange")
        self.mode_field = BoundField(editor, "Mode", "gasexchange.mode", "choice", choices=MODE_CHOICES)
        self.mode_field.valueChanged.connect(lambda _p: self.sync_tabs())
        mode_box.addField(self.mode_field)
        layout.addWidget(mode_box)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.setTabPosition(QTabWidget.North)
        self.valve_tab = ValveEditorTab(editor)
        self.port_tab = PortEditorTab(editor)
        self.slot_tab = SlotEditorTab(editor)
        layout.addWidget(self.tabs, 1)
        self.sync_tabs()

    def sync_tabs(self) -> None:
        mode = self.editor.active_gasexchange_mode()
        current = self.tabs.currentWidget()
        self.tabs.clear()
        if mode == "ports":
            self.tabs.addTab(self.port_tab, "Ports")
            self.tabs.setCurrentWidget(self.port_tab)
        elif mode == "slots":
            self.tabs.addTab(self.slot_tab, "Slots")
            self.tabs.setCurrentWidget(self.slot_tab)
        else:
            self.tabs.addTab(self.valve_tab, "Valves")
            self.tabs.setCurrentWidget(self.valve_tab)
        if current is not None and current in (self.valve_tab, self.port_tab, self.slot_tab):
            try:
                self.tabs.setCurrentWidget(current)
            except Exception:
                pass


class TimingPreviewWidget(QWidget):
    def __init__(self, editor: "EngineGasExchangeEditor") -> None:
        super().__init__()
        self.editor = editor
        self.setMinimumSize(QSize(920, 420))

    def _draw_aligned_text(self, painter: QPainter, rect: QRect, alignment_name: str, text: str) -> None:
        alignment = {
            "left": Qt.AlignLeft,
            "center": Qt.AlignHCenter,
            "right": Qt.AlignRight,
        }.get(alignment_name, Qt.AlignLeft)
        painter.drawText(rect, alignment | Qt.AlignVCenter, text)

    def paintEvent(self, _event) -> None:
        style = self.editor.preview_style
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(style.background_color))

        font = QFont(style.font_family, style.font_size)
        painter.setFont(font)
        painter.setPen(QPen(QColor(style.text_color), 1.0))
        metrics = painter.fontMetrics()

        outer = self.rect().adjusted(14, 12, -14, -16)
        if outer.width() < 360 or outer.height() < 240:
            return

        cycle_type = self.editor.cycle_type()
        x_min, x_max = self.editor.current_plot_range()
        span = max(x_max - x_min, 1.0)

        x_values: list[float] = []
        intake: list[float] = []
        exhaust: list[float] = []
        right_axis_curve: list[float] = []

        stroke = self.editor.engine_value("stroke_m")
        conrod = self.editor.engine_value("conrod_m")
        bore = self.editor.engine_value("bore_m")
        compression_ratio = self.editor.engine_value("compression_ratio")

        approx_points = max(120, min(540, int(self.width() * 0.55)))
        step = max(span / max(approx_points - 1, 1), 0.5)
        theta = x_min
        left_max_data = 0.0
        right_max_data = 0.0

        while theta <= x_max + 1e-9:
            normalized = normalize_theta(theta, cycle_type)
            left_in, left_ex = self.editor.preview_pair(normalized)
            right_value = self.editor.preview_right_axis_value(bore, stroke, conrod, compression_ratio, normalized)

            x_values.append(theta)
            intake.append(left_in)
            exhaust.append(left_ex)
            right_axis_curve.append(right_value)
            left_max_data = max(left_max_data, left_in, left_ex)
            right_max_data = max(right_max_data, right_value)
            theta += step

        left_axis_min = float(style.y_axis_min)
        if self.editor.auto_fit_left_axis:
            left_axis_max = nice_axis_max(max(left_max_data * 1.12, left_axis_min + 1e-12))
            self.editor.manual_left_axis_max = left_axis_max
        else:
            left_axis_max = max(float(style.y_axis_max), left_axis_min + 1e-12)
            self.editor.manual_left_axis_max = left_axis_max
        left_axis_step = float(style.y_axis_step) if style.y_axis_step > 0 else max((left_axis_max - left_axis_min) / 4.0, 1e-6)
        left_ticks = axis_ticks(left_axis_min, left_axis_max, left_axis_step)

        right_axis_max = nice_axis_max(max(right_max_data * 1.12, 1e-12))
        self.editor.manual_right_axis_max = right_axis_max
        right_ticks = nice_ticks(right_axis_max, 4)

        left_label_width = max(metrics.horizontalAdvance(compact_number(tick, digits=6)) for tick in left_ticks)
        right_label_width = max(metrics.horizontalAdvance(compact_number(tick, digits=6)) for tick in right_ticks)
        left_margin = max(82, left_label_width + 18)
        right_margin = max(196, right_label_width + 132)
        plot = outer.adjusted(left_margin, 42, -right_margin, -68)
        if plot.width() < 120 or plot.height() < 120:
            return

        left_span = max(left_axis_max - left_axis_min, 1e-12)

        def x_to_px(x_deg: float) -> float:
            return plot.left() + (x_deg - x_min) / span * plot.width()

        def y_left_to_px(value: float) -> float:
            return plot.bottom() - ((value - left_axis_min) / left_span) * plot.height()

        def y_right_to_px(value: float) -> float:
            return plot.bottom() - (value / right_axis_max) * plot.height()

        if style.grid_visible:
            for grid_value in self.editor.x_grid_values():
                x = x_to_px(grid_value)
                major = self.editor.is_major_x_grid_value(grid_value)
                color = QColor(style.grid_color)
                width = 1.3 if major else 1.0
                painter.setPen(QPen(color, width, pen_style(style.grid_style)))
                painter.drawLine(int(x), plot.top(), int(x), plot.bottom())
            for tick in left_ticks:
                y = y_left_to_px(tick)
                painter.setPen(QPen(QColor(style.grid_color), 1.0, pen_style(style.grid_style)))
                painter.drawLine(plot.left(), int(y), plot.right(), int(y))

        painter.setPen(QPen(QColor(style.frame_color), 1.0))
        painter.drawRect(plot)

        def draw_series(values: list[float], color: str, width: float, y_map, dashed: bool = False) -> None:
            painter.setPen(QPen(QColor(color), width, Qt.DashLine if dashed else Qt.SolidLine))
            last: tuple[float, float] | None = None
            for x_value, y_value in zip(x_values, values):
                point = (x_to_px(x_value), y_map(y_value))
                if last is not None:
                    painter.drawLine(int(last[0]), int(last[1]), int(point[0]), int(point[1]))
                last = point

        draw_series(intake, style.intake_color, 2.0, y_left_to_px)
        draw_series(exhaust, style.exhaust_color, 2.0, y_left_to_px)
        draw_series(right_axis_curve, style.aux_color, 1.6, y_right_to_px, dashed=True)

        marker_x = x_to_px(clamp(self.editor.preview_angle_deg, x_min, x_max))
        painter.setPen(QPen(QColor(style.frame_color), 1.1, Qt.DotLine))
        painter.drawLine(int(marker_x), plot.top(), int(marker_x), plot.bottom())

        title = style.timing_title.strip() or f"Timing preview – {self.editor.active_display_mode_title()}"
        painter.setPen(QPen(QColor(style.text_color), 1.0))
        self._draw_aligned_text(painter, QRect(plot.left(), outer.top(), plot.width(), 18), style.title_alignment, title)

        left_title = style.left_axis_title.strip() or f"{self.editor.active_left_axis_title()} [{self.editor.active_left_axis_unit()}]"
        right_title = style.right_axis_title.strip() or f"{self.editor.active_right_axis_title()} [{self.editor.active_right_axis_unit()}]"
        x_title = style.x_axis_title.strip() or "Kurbelwinkel [deg]"

        self._draw_aligned_text(painter, QRect(plot.left(), plot.top() - 18, plot.width(), 16), style.axis_title_alignment, left_title)
        painter.save()
        right_axis_title_x = plot.right() + right_label_width + 104
        painter.translate(right_axis_title_x, plot.center().y())
        painter.rotate(-90)
        painter.drawText(QRect(-plot.height() // 2, -72, plot.height(), 28), Qt.AlignCenter, right_title)
        painter.restore()

        for tick in self.editor.x_tick_values():
            x = x_to_px(tick)
            text = f"{compact_number(tick, digits=6)}°"
            text_width = metrics.horizontalAdvance(text)
            painter.drawText(int(x - text_width * 0.5), plot.bottom() + 22, text)
        self._draw_aligned_text(painter, QRect(plot.left(), plot.bottom() + 34, plot.width(), 18), style.axis_title_alignment, x_title)

        for tick in left_ticks:
            y = y_left_to_px(tick)
            painter.drawText(plot.left() - left_label_width - 8, int(y) + 4, compact_number(tick, digits=6))
        for tick in right_ticks:
            y = y_right_to_px(tick)
            painter.drawText(plot.right() + 10, int(y) + 4, compact_number(tick, digits=6))

        preview_info = f"y_max={compact_number(left_axis_max, digits=6)} {self.editor.active_left_axis_unit()} | Basis {self.editor.valve_lift_basis_summary()}"
        preview_info_width = metrics.horizontalAdvance(preview_info)
        painter.drawText(plot.right() - preview_info_width, plot.top() - 6, preview_info)

        legend_items = [
            ("Intake", style.intake_color, False),
            ("Exhaust", style.exhaust_color, False),
            (self.editor.active_right_axis_legend_label(), style.aux_color, True),
        ]
        if style.legend_position.startswith("top"):
            legend_y = outer.top() + 18
        else:
            legend_y = plot.bottom() + 56
        if style.legend_position.endswith("right"):
            legend_x = plot.right() - 310
        else:
            legend_x = plot.left() + 8
        for name, color, dashed in legend_items:
            painter.setPen(QPen(QColor(color), 2.0, Qt.DashLine if dashed else Qt.SolidLine))
            painter.drawLine(legend_x, legend_y, legend_x + 20, legend_y)
            painter.setPen(QPen(QColor(style.text_color), 1.0))
            painter.drawText(legend_x + 26, legend_y + 5, name)
            legend_x += 105


class SectionPreviewWidget(QWidget):
    def __init__(self, editor: "EngineGasExchangeEditor") -> None:
        super().__init__()
        self.editor = editor
        self.setMinimumSize(QSize(760, 520))

    def paintEvent(self, _event) -> None:
        style = self.editor.preview_style
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(style.background_color))
        painter.setFont(QFont(style.font_family, style.font_size))

        rect = self.rect().adjusted(18, 16, -18, -16)
        if rect.width() < 260 or rect.height() < 260:
            return

        cycle_type = self.editor.cycle_type()
        theta = normalize_theta(self.editor.preview_angle_deg, cycle_type)

        bore = self.editor.engine_value("bore_m")
        stroke = self.editor.engine_value("stroke_m")
        conrod = self.editor.engine_value("conrod_m")
        compression_ratio = self.editor.engine_value("compression_ratio")
        clearance_height = self.editor.estimated_clearance_height()
        piston_from_ut = piston_distance_from_ut(stroke, conrod, theta)

        total_height = clearance_height + stroke + 0.05
        scale = min(rect.width() / max(bore * 2.6, 1e-12), rect.height() / max(total_height * 1.16, 1e-12))
        cx = rect.center().x()
        head_y = rect.top() + 40
        liner_left = cx - bore * 0.5 * scale
        liner_right = cx + bore * 0.5 * scale
        liner_bottom = head_y + (clearance_height + stroke) * scale
        piston_top = head_y + (clearance_height + (stroke - piston_from_ut)) * scale
        piston_height_px = max(22, int(0.12 * stroke * scale))

        painter.setPen(QPen(QColor(style.frame_color), 2.0))
        painter.drawLine(int(liner_left), int(head_y), int(liner_left), int(liner_bottom))
        painter.drawLine(int(liner_right), int(head_y), int(liner_right), int(liner_bottom))
        painter.drawLine(int(liner_left), int(head_y), int(liner_right), int(head_y))

        painter.setPen(QPen(QColor(style.frame_color), 1.0, Qt.DashLine))
        chamber_roof_y = head_y + 8
        painter.drawLine(int(liner_left + 6), int(chamber_roof_y), int(liner_right - 6), int(chamber_roof_y))
        painter.setPen(QPen(QColor(style.text_color), 1.0))
        painter.drawText(int(liner_left + 10), int(chamber_roof_y - 8), "Brennraumdach")

        painter.setBrush(QColor(style.section_metal_color))
        painter.setPen(QPen(QColor(style.frame_color), 1.3))
        piston_rect = QRect(int(liner_left + 2), int(piston_top), int(liner_right - liner_left - 4), piston_height_px)
        painter.drawRect(piston_rect)
        painter.drawLine(piston_rect.left(), piston_rect.bottom() + 6, piston_rect.right(), piston_rect.bottom() + 6)

        mode = self.editor.active_gasexchange_mode()
        if mode == "valves":
            self._draw_valves(painter, liner_left, liner_right, head_y, theta, scale)
        else:
            self._draw_windows(painter, liner_left, liner_right, liner_bottom, theta, mode, scale)

        title = style.section_title.strip() or "Section preview"
        painter.setPen(QPen(QColor(style.text_color), 1.0))
        painter.drawText(rect.left(), rect.top() + 4, title)
        volume_text = compact_number(
            self.editor.plot_volume_from_m3(cylinder_volume_m3(bore, stroke, conrod, compression_ratio, theta)),
            digits=6,
        )
        painter.drawText(
            rect.left(),
            rect.bottom() - 4,
            f"Winkel {compact_number(theta)}° | Zyklus {cycle_type} | Volumen {volume_text} {self.editor.plot_volume_unit()}",
        )

    def _draw_valves(self, painter: QPainter, liner_left: float, liner_right: float, head_y: float, theta: float, scale: float) -> None:
        style = self.editor.preview_style
        intake_lift = self.editor.compute_valve_lift("intake", theta)
        exhaust_lift = self.editor.compute_valve_lift("exhaust", theta)
        intake_x = liner_left + 0.32 * (liner_right - liner_left)
        exhaust_x = liner_left + 0.68 * (liner_right - liner_left)

        def draw_valve(x: float, lift: float, label: str, color: str) -> None:
            painter.setPen(QPen(QColor(color), 2.0))
            diameter_px = 20.0
            disc_rect = QRect(int(x - diameter_px * 0.5), int(head_y - 8), int(diameter_px), 14)
            painter.drawEllipse(disc_rect)
            lift_px = max(0.0, lift * scale * 18.0)
            painter.drawLine(int(x), int(head_y), int(x), int(head_y + lift_px + 18))
            painter.drawLine(int(x - 6), int(head_y + lift_px), int(x + 6), int(head_y + lift_px))
            painter.setPen(QPen(QColor(style.text_color), 1.0))
            painter.drawText(int(x - 28), int(head_y - 14), label)

        draw_valve(intake_x, intake_lift, "Intake", style.intake_color)
        draw_valve(exhaust_x, exhaust_lift, "Exhaust", style.exhaust_color)

    def _draw_windows(
        self,
        painter: QPainter,
        liner_left: float,
        liner_right: float,
        liner_bottom: float,
        theta: float,
        mode: str,
        scale: float,
    ) -> None:
        style = self.editor.preview_style
        for side, color, anchor_x, direction, label in (
            ("intake", style.intake_color, liner_left, -1.0, "Intake"),
            ("exhaust", style.exhaust_color, liner_right, 1.0, "Exhaust"),
        ):
            geom = self.editor.window_section_geometry(side, theta, mode)
            width_px = max(14.0, geom["width_m"] * scale * 1.8)
            full_height_px = max(12.0, geom["height_m"] * scale)
            open_height_px = max(0.0, geom["open_height_m"] * scale)
            offset_px = geom["offset_m"] * scale
            top_y = liner_bottom - offset_px - full_height_px
            rect_x = anchor_x - width_px if direction < 0 else anchor_x
            rect = QRect(int(rect_x), int(top_y), int(width_px), int(full_height_px))

            painter.setPen(QPen(QColor(color), 2.0))
            painter.setBrush(Qt.NoBrush)
            painter.drawRect(rect)

            if open_height_px > 0.0:
                open_rect = QRect(rect.left(), rect.top(), rect.width(), int(open_height_px))
                painter.fillRect(open_rect, QColor(color).lighter(170))
                painter.setPen(QPen(QColor(color), 1.0))
                painter.drawRect(open_rect)
            covered_height = max(0.0, rect.height() - int(open_height_px))
            if covered_height > 0:
                cover_rect = QRect(rect.left(), rect.top() + int(open_height_px), rect.width(), covered_height)
                painter.fillRect(cover_rect, QColor(style.section_cover_color))

            bridge_x = rect.right() if direction < 0 else rect.left()
            painter.setPen(QPen(QColor(style.frame_color), 1.2))
            painter.drawLine(int(bridge_x), int(rect.center().y()), int(anchor_x), int(rect.center().y()))

            self._draw_roof(painter, rect, geom["roof"], direction < 0)
            painter.setPen(QPen(QColor(style.text_color), 1.0))
            painter.drawText(rect.left() - 8 if direction < 0 else rect.left() + 6, rect.top() - 8, f"{label} ×{geom['count']}")

        painter.setPen(QPen(QColor(style.text_color), 1.0))
        painter.drawText(int(liner_left + 10), int(liner_bottom - 10), "Feste Geometrie konstant, nur Freigabe/Abdeckung ändert sich")

    def _draw_roof(self, painter: QPainter, rect: QRect, roof: dict[str, float | str], left_side: bool) -> None:
        roof_type = str(roof.get("type", "none") or "none")
        if roof_type == "none":
            return
        color = QColor("#5b5b5b")
        painter.setPen(QPen(color, 1.4))
        roof_len_px = float(roof.get("len_px", 0.0) or 0.0)
        roof_gamma = float(roof.get("gamma", 1.0) or 1.0)
        roof_angle = float(roof.get("angle_deg", 20.0) or 20.0)
        cx = rect.center().x()
        base_y = rect.top()
        if roof_type == "angle":
            dx = max(10.0, abs(math.tan(math.radians(roof_angle))) * 18.0)
            sx = cx - dx if left_side else cx + dx
            painter.drawLine(int(sx), int(base_y - max(10.0, roof_len_px * 0.6)), int(cx), int(base_y))
        elif roof_type == "factor":
            width = max(24, rect.width())
            height = max(10, int(max(roof_len_px, 8.0) * max(roof_gamma, 0.1)))
            painter.drawArc(int(cx - width * 0.5), int(base_y - height), width, height, 0, 180 * 16)
        elif roof_type == "linear":
            dx = max(10.0, roof_len_px * 0.8)
            sx = cx - dx if left_side else cx + dx
            painter.drawLine(int(sx), int(base_y - max(8.0, roof_len_px)), int(cx), int(base_y))
        else:
            width = max(24, rect.width())
            height = max(10, int(max(roof_len_px, 8.0)))
            painter.drawArc(int(cx - width * 0.5), int(base_y - height), width, height, 0, 180 * 16)


class PreviewStyleDialog(QDialog):
    styleChanged = Signal(object)
    resetRequested = Signal()

    def __init__(self, parent: QWidget | None, style: PreviewStyleConfig) -> None:
        super().__init__(parent)
        self.setWindowTitle("Preview- / Diagramm-Eigenschaften")
        self.setModal(False)
        self.resize(760, 620)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        scroll.setWidget(content)
        form_layout = QVBoxLayout(content)
        form_layout.setContentsMargins(0, 0, 0, 0)
        form_layout.setSpacing(10)
        layout.addWidget(scroll, 1)

        general = ResponsiveFormBox("Allgemein")
        self.font_family = QFontComboBox()
        self.font_family.currentFontChanged.connect(self._emit)
        self.font_size = QSpinBox()
        self.font_size.setRange(6, 48)
        self.font_size.valueChanged.connect(self._emit)
        self.grid_visible = QCheckBox("Grid sichtbar")
        self.grid_visible.toggled.connect(self._emit)
        self.grid_style = QComboBox()
        self.grid_style.addItems(GRID_STYLE_CHOICES)
        self.grid_style.currentIndexChanged.connect(self._emit)
        self.legend_position = QComboBox()
        self.legend_position.addItems(LEGEND_POSITIONS)
        self.legend_position.currentIndexChanged.connect(self._emit)
        self.title_alignment = QComboBox()
        self.title_alignment.addItems(ALIGN_CHOICES)
        self.title_alignment.currentIndexChanged.connect(self._emit)
        self.axis_title_alignment = QComboBox()
        self.axis_title_alignment.addItems(ALIGN_CHOICES)
        self.axis_title_alignment.currentIndexChanged.connect(self._emit)

        general.addField(self._wrap_widget("Schriftart", self.font_family))
        general.addField(self._wrap_widget("Schriftgröße", self.font_size))
        general.addField(self._wrap_widget("Grid sichtbar", self.grid_visible))
        general.addField(self._wrap_widget("Grid-Stil", self.grid_style))
        general.addField(self._wrap_widget("Legendenposition", self.legend_position))
        general.addField(self._wrap_widget("Titel-Ausrichtung", self.title_alignment))
        general.addField(self._wrap_widget("Achsentitel-Ausr.", self.axis_title_alignment))
        form_layout.addWidget(general)

        text_box = ResponsiveFormBox("Titel / Achsentitel")
        self.timing_title = self._line_edit(text_box, "Timing title")
        self.section_title = self._line_edit(text_box, "Section title")
        self.x_axis_title = self._line_edit(text_box, "X axis title")
        self.left_axis_title = self._line_edit(text_box, "Left axis title")
        self.right_axis_title = self._line_edit(text_box, "Right axis title")
        form_layout.addWidget(text_box)

        axes_box = ResponsiveFormBox("Achsen / Grid")
        self.y_axis_min = CompactDoubleSpinBox()
        self.y_axis_min.setDecimals(6)
        self.y_axis_min.setRange(-1.0e9, 1.0e9)
        self.y_axis_min.valueChanged.connect(self._emit)
        self.y_axis_max = CompactDoubleSpinBox()
        self.y_axis_max.setDecimals(6)
        self.y_axis_max.setRange(-1.0e9, 1.0e9)
        self.y_axis_max.valueChanged.connect(self._emit)
        self.y_axis_step = CompactDoubleSpinBox()
        self.y_axis_step.setDecimals(6)
        self.y_axis_step.setRange(1.0e-6, 1.0e9)
        self.y_axis_step.valueChanged.connect(self._emit)
        self.x_grid_step_deg = CompactDoubleSpinBox()
        self.x_grid_step_deg.setDecimals(3)
        self.x_grid_step_deg.setRange(1.0, 1440.0)
        self.x_grid_step_deg.valueChanged.connect(self._emit)
        self.x_major_grid_step_deg = CompactDoubleSpinBox()
        self.x_major_grid_step_deg.setDecimals(3)
        self.x_major_grid_step_deg.setRange(1.0, 1440.0)
        self.x_major_grid_step_deg.valueChanged.connect(self._emit)
        axes_box.addField(self._wrap_widget("Y min links", self.y_axis_min))
        axes_box.addField(self._wrap_widget("Y max links", self.y_axis_max))
        axes_box.addField(self._wrap_widget("Y Schritt links", self.y_axis_step))
        axes_box.addField(self._wrap_widget("X Grid Teilung [deg]", self.x_grid_step_deg))
        axes_box.addField(self._wrap_widget("X Hauptgrid [deg]", self.x_major_grid_step_deg))
        form_layout.addWidget(axes_box)

        colors = ResponsiveFormBox("Farben")
        self.text_color = self._color_field(colors, "Textfarbe")
        self.background_color = self._color_field(colors, "Hintergrund")
        self.grid_color = self._color_field(colors, "Gridfarbe")
        self.frame_color = self._color_field(colors, "Rahmen / Achsen")
        self.intake_color = self._color_field(colors, "Intake-Linie")
        self.exhaust_color = self._color_field(colors, "Exhaust-Linie")
        self.aux_color = self._color_field(colors, "Hilfskurve")
        self.section_metal_color = self._color_field(colors, "Section Metall")
        self.section_cover_color = self._color_field(colors, "Section Abdeckung")
        form_layout.addWidget(colors)

        json_box = ResponsiveFormBox("JSON Preview")
        self.json_font_family = QFontComboBox()
        self.json_font_family.currentFontChanged.connect(self._emit)
        self.json_font_size = QSpinBox()
        self.json_font_size.setRange(6, 40)
        self.json_font_size.valueChanged.connect(self._emit)
        self.json_background_color = self._color_field(json_box, "JSON Hintergrund")
        self.json_text_color = self._color_field(json_box, "JSON Text")
        json_box.addField(self._wrap_widget("JSON Schriftart", self.json_font_family))
        json_box.addField(self._wrap_widget("JSON Schriftgröße", self.json_font_size))
        form_layout.addWidget(json_box)
        form_layout.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        self.reset_button = buttons.addButton("Zurücksetzen", QDialogButtonBox.ResetRole)
        self.reset_button.clicked.connect(self.resetRequested.emit)
        buttons.rejected.connect(self.close)
        layout.addWidget(buttons)

        self.set_style(style)

    def _wrap_widget(self, title: str, widget: QWidget) -> QWidget:
        wrapper = QWidget()
        row = QHBoxLayout(wrapper)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        label = QLabel(title)
        label.setMinimumWidth(FORM_LABEL_MIN_WIDTH)
        row.addWidget(label)
        widget.setMinimumWidth(max(widget.minimumWidth(), FORM_EDITOR_MIN_WIDTH))
        row.addWidget(widget, 1)
        return wrapper

    def _line_edit(self, box: ResponsiveFormBox, title: str) -> QLineEdit:
        edit = QLineEdit()
        edit.textChanged.connect(self._emit)
        box.addField(self._wrap_widget(title, edit))
        return edit

    def _color_field(self, box: ResponsiveFormBox, title: str) -> ColorButton:
        button = ColorButton("#ffffff")
        button.colorChanged.connect(self._emit)
        box.addField(self._wrap_widget(title, button))
        return button

    def set_style(self, style: PreviewStyleConfig) -> None:
        self.blockSignals(True)
        self.font_family.setCurrentFont(QFont(style.font_family))
        self.font_size.setValue(style.font_size)
        self.grid_visible.setChecked(style.grid_visible)
        self.grid_style.setCurrentText(style.grid_style)
        self.legend_position.setCurrentText(style.legend_position)
        self.title_alignment.setCurrentText(style.title_alignment)
        self.axis_title_alignment.setCurrentText(style.axis_title_alignment)
        self.timing_title.setText(style.timing_title)
        self.section_title.setText(style.section_title)
        self.x_axis_title.setText(style.x_axis_title)
        self.left_axis_title.setText(style.left_axis_title)
        self.right_axis_title.setText(style.right_axis_title)
        self.y_axis_min.setValue(float(style.y_axis_min))
        self.y_axis_max.setValue(float(style.y_axis_max))
        self.y_axis_step.setValue(float(style.y_axis_step))
        self.x_grid_step_deg.setValue(float(style.x_grid_step_deg))
        self.x_major_grid_step_deg.setValue(float(style.x_major_grid_step_deg))
        self.text_color.setColor(style.text_color)
        self.background_color.setColor(style.background_color)
        self.grid_color.setColor(style.grid_color)
        self.frame_color.setColor(style.frame_color)
        self.intake_color.setColor(style.intake_color)
        self.exhaust_color.setColor(style.exhaust_color)
        self.aux_color.setColor(style.aux_color)
        self.section_metal_color.setColor(style.section_metal_color)
        self.section_cover_color.setColor(style.section_cover_color)
        self.json_font_family.setCurrentFont(QFont(style.json_font_family))
        self.json_font_size.setValue(style.json_font_size)
        self.json_background_color.setColor(style.json_background_color)
        self.json_text_color.setColor(style.json_text_color)
        self.blockSignals(False)

    def current_style(self) -> PreviewStyleConfig:
        return PreviewStyleConfig(
            font_family=self.font_family.currentFont().family(),
            font_size=int(self.font_size.value()),
            text_color=self.text_color.color(),
            background_color=self.background_color.color(),
            grid_visible=self.grid_visible.isChecked(),
            grid_color=self.grid_color.color(),
            grid_style=self.grid_style.currentText(),
            legend_position=self.legend_position.currentText(),
            title_alignment=self.title_alignment.currentText(),
            axis_title_alignment=self.axis_title_alignment.currentText(),
            timing_title=self.timing_title.text().strip(),
            section_title=self.section_title.text().strip(),
            x_axis_title=self.x_axis_title.text().strip(),
            left_axis_title=self.left_axis_title.text().strip(),
            right_axis_title=self.right_axis_title.text().strip(),
            y_axis_min=float(self.y_axis_min.value()),
            y_axis_max=float(self.y_axis_max.value()),
            y_axis_step=float(self.y_axis_step.value()),
            x_grid_step_deg=float(self.x_grid_step_deg.value()),
            x_major_grid_step_deg=float(self.x_major_grid_step_deg.value()),
            intake_color=self.intake_color.color(),
            exhaust_color=self.exhaust_color.color(),
            aux_color=self.aux_color.color(),
            frame_color=self.frame_color.color(),
            json_font_family=self.json_font_family.currentFont().family(),
            json_font_size=int(self.json_font_size.value()),
            json_background_color=self.json_background_color.color(),
            json_text_color=self.json_text_color.color(),
            section_metal_color=self.section_metal_color.color(),
            section_cover_color=self.section_cover_color.color(),
        )

    def _emit(self, *_args: Any) -> None:
        self.styleChanged.emit(self.current_style())


class EngineGasExchangeEditor(QMainWindow):
    def __init__(self, config_path: str | Path | None = None) -> None:
        super().__init__()
        self.setWindowTitle("EngineGasExchangeEditor")

        self.settings = QSettings(APP_ORG, APP_NAME)
        self.loading_ui = False
        self.current_path: Path | None = None
        self.bindables: list[Any] = []
        self.thread_pool = QThreadPool.globalInstance()
        self.preview_style = PreviewStyleConfig.from_settings(self.settings)
        self.file_preview_popup = FilePreviewPopup()
        self.file_preview_cache: dict[tuple[str, int], dict[str, Any]] = {}
        self._lift_profile_cache: dict[tuple[str, float, str], list[tuple[float, float]]] = {}
        self._alpha_k_profile_cache: dict[str, list[tuple[float, float, float]]] = {}
        self._file_preview_timer = QTimer(self)
        self._file_preview_timer.setSingleShot(True)
        self._file_preview_timer.timeout.connect(self._show_pending_file_preview)
        self._hide_preview_timer = QTimer(self)
        self._hide_preview_timer.setSingleShot(True)
        self._hide_preview_timer.timeout.connect(self.file_preview_popup.hide)
        self._pending_preview_anchor: QWidget | None = None
        self._pending_preview_path = ""
        self._preview_request_token = 0
        self._active_preview_token = 0

        self.config_data: dict[str, Any] = self.default_config()
        self.engine_save_aliases: dict[str, str] = {"bore_m": "bore_m", "stroke_m": "stroke_m", "conrod_m": "conrod_m"}

        self.unit_mode = str(self.settings.value("ui/unit_mode", "si"))
        if self.unit_mode not in {"si", "eng"}:
            self.unit_mode = "si"
        self.display_mode = str(self.settings.value("ui/display_mode", AREA_MODE))
        if self.display_mode not in DISPLAY_MODE_LABELS:
            self.display_mode = AREA_MODE
        self.right_axis_mode = str(self.settings.value("ui/right_axis_mode", RIGHT_AXIS_PISTON_MODE))
        if self.right_axis_mode not in RIGHT_AXIS_MODE_LABELS:
            self.right_axis_mode = RIGHT_AXIS_PISTON_MODE
        self.start_plot_from_zero = self.settings.value("ui/start_from_zero", False, type=bool)
        self.auto_fit_left_axis = self.settings.value("ui/auto_fit_left_axis", self.settings.value("ui/auto_fit_preview", True, type=bool), type=bool)
        self.preview_angle_deg = float(self.settings.value("ui/preview_angle_deg", 180.0))
        self.manual_left_axis_max = float(self.settings.value("ui/manual_left_axis_max", 1.0))
        self.manual_right_axis_max = float(self.settings.value("ui/manual_right_axis_max", 1.0))
        self.last_cycle_type = str(self.settings.value("ui/last_cycle_type", "4T")).upper()
        if self.last_cycle_type not in CYCLE_CHOICES:
            self.last_cycle_type = "4T"

        self._build_window()
        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self._build_docks()
        self._populate_style_menu()
        self._apply_saved_style()
        self._restore_layout()

        initial_path: Path | None = None
        if config_path:
            initial_path = Path(config_path)
        else:
            last_path_text = str(self.settings.value("files/last_config_path", "") or "").strip()
            if last_path_text:
                candidate = Path(last_path_text).expanduser()
                if candidate.exists():
                    initial_path = candidate
        if initial_path is not None:
            self.load_json(Path(initial_path))
        else:
            deep_set(self.config_data, "engine.cycle_type", self.last_cycle_type)
            self.ensure_defaults()
            self.refresh_ui_from_model()

        self._restore_view_state()
        self.showMaximized()
        self.statusBar().showMessage("Bereit", 2500)

    def register_bindable(self, widget: Any) -> None:
        self.bindables.append(widget)

    def default_config(self) -> dict[str, Any]:
        return {
            "engine": {
                "cycle_type": "4T",
                "bore_m": 0.086,
                "stroke_m": 0.086,
                "conrod_m": 0.143,
                "compression_ratio": 10.5,
            },
            "gasexchange": {
                "mode": "valves",
                "valves": {
                    "lift_file": "",
                    "alphak_file": "",
                    "lift_angle_basis": "cam",
                    "cam_to_crank_ratio": 2.0,
                    "effective_lift_threshold_mm": 0.1,
                    "scaling": {
                        "intake": {
                            "angle_scale": 1.0,
                            "lift_scale": 1.0,
                        },
                        "exhaust": {
                            "angle_scale": 1.0,
                            "lift_scale": 1.0,
                        },
                    },
                    "count_in": 2,
                    "count_ex": 2,
                    "intake": {
                        "lift_file": "",
                        "alphak_file": "",
                        "profile_angle_domain": "cam",
                        "open_deg": 350.0,
                        "max_lift_m": 0.010,
                    },
                    "exhaust": {
                        "lift_file": "",
                        "alphak_file": "",
                        "profile_angle_domain": "cam",
                        "open_deg": 135.0,
                        "max_lift_m": 0.009,
                    },
                },
                "ports": {
                    "area_file": "",
                    "alphak_file": "",
                    "intake": {
                        "width_m": 0.018,
                        "height_m": 0.022,
                        "count": 4,
                        "offset_from_ut_m": 0.012,
                        "alphak_file": "",
                        "roof": {"type": "linear", "len_m": 0.004, "gamma": 1.0, "angle_deg": 18.0},
                    },
                    "exhaust": {
                        "width_m": 0.020,
                        "height_m": 0.024,
                        "count": 3,
                        "offset_from_ut_m": 0.010,
                        "alphak_file": "",
                        "roof": {"type": "linear", "len_m": 0.004, "gamma": 1.0, "angle_deg": 18.0},
                    },
                },
                "slots": {
                    "forward_discharge_coefficient": 1.0,
                    "reverse_discharge_coefficient": 1.0,
                    "intake": {
                        "width_m": 0.010,
                        "height_m": 0.020,
                        "count": 8,
                        "offset_from_ut_m": 0.015,
                        "forward_discharge_coefficient": 1.0,
                        "reverse_discharge_coefficient": 1.0,
                        "roof": {"type": "cos", "len_m": 0.004, "gamma": 1.2, "angle_deg": 20.0},
                    },
                    "exhaust": {
                        "width_m": 0.012,
                        "height_m": 0.022,
                        "count": 6,
                        "offset_from_ut_m": 0.012,
                        "forward_discharge_coefficient": 1.0,
                        "reverse_discharge_coefficient": 1.0,
                        "roof": {"type": "cos", "len_m": 0.004, "gamma": 1.2, "angle_deg": 20.0},
                    },
                },
            },
        }

    def _build_window(self) -> None:
        self.setDockOptions(
            QMainWindow.AllowNestedDocks
            | QMainWindow.AllowTabbedDocks
            | QMainWindow.GroupedDragging
            | QMainWindow.AnimatedDocks
        )
        central = QWidget()
        central.setMinimumSize(0, 0)
        central.setMaximumSize(0, 0)
        central.hide()
        self.setCentralWidget(central)

    def _build_actions(self) -> None:
        self.act_load = QAction("Laden", self)
        self.act_save = QAction("Speichern", self)
        self.act_save_as = QAction("Speichern unter", self)
        self.act_quit = QAction("Beenden", self)
        self.act_layout_save = QAction("Layout speichern", self)
        self.act_layout_reset = QAction("Layout zurücksetzen", self)
        self.act_preview_style = QAction("Preview-/Diagramm-Eigenschaften", self)
        self.act_preview_style_reset = QAction("Preview-/Diagramm-Stile zurücksetzen", self)

        self.act_load.triggered.connect(self.load_json_via_dialog)
        self.act_save.triggered.connect(self.save_json)
        self.act_save_as.triggered.connect(self.save_json_as)
        self.act_quit.triggered.connect(self.close)
        self.act_layout_save.triggered.connect(self.save_layout_to_settings)
        self.act_layout_reset.triggered.connect(self.reset_layout)
        self.act_preview_style.triggered.connect(self.open_preview_style_dialog)
        self.act_preview_style_reset.triggered.connect(self.reset_preview_style)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Datei")
        file_menu.addAction(self.act_load)
        file_menu.addAction(self.act_save)
        file_menu.addAction(self.act_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        self.view_menu = self.menuBar().addMenu("Ansicht")
        self.view_menu.addAction(self.act_layout_save)
        self.view_menu.addAction(self.act_layout_reset)
        self.view_menu.addSeparator()

        self.style_menu = self.menuBar().addMenu("Style")
        self.style_action_group = QActionGroup(self)
        self.style_action_group.setExclusive(True)

        preview_menu = self.menuBar().addMenu("Preview / Diagramm")
        preview_menu.addAction(self.act_preview_style)
        preview_menu.addAction(self.act_preview_style_reset)

    def _build_toolbar(self) -> None:
        toolbar = QToolBar("Main", self)
        toolbar.setObjectName("main_toolbar")
        toolbar.setMovable(False)
        toolbar.setFloatable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        toolbar.addAction(self.act_load)
        toolbar.addAction(self.act_save)
        toolbar.addSeparator()

        self.unit_toggle = QToolButton()
        self.unit_toggle.setCheckable(True)
        self.unit_toggle.setToolTip("Toggle SI / Engineering Units")
        self.unit_toggle.toggled.connect(self.toggle_unit_mode)
        toolbar.addWidget(self.unit_toggle)

        self.cycle_toggle = QToolButton()
        self.cycle_toggle.setCheckable(True)
        self.cycle_toggle.setToolTip("Toggle 2T / 4T")
        self.cycle_toggle.toggled.connect(self.toggle_cycle_toolbar)
        toolbar.addWidget(self.cycle_toggle)

        self.zero_toggle = QToolButton()
        self.zero_toggle.setCheckable(True)
        self.zero_toggle.setText("Diagramm ab 0°")
        self.zero_toggle.toggled.connect(self.toggle_zero_start)
        toolbar.addWidget(self.zero_toggle)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Anzeige"))
        self.display_mode_combo = QComboBox()
        for key in (AREA_MODE, LIFT_MODE, HEIGHT_MODE):
            self.display_mode_combo.addItem(DISPLAY_MODE_LABELS[key], key)
        self.display_mode_combo.currentIndexChanged.connect(self.change_display_mode_from_toolbar)
        self.display_mode_combo.setMinimumWidth(210)
        toolbar.addWidget(self.display_mode_combo)

        self.preview_ut_button = QToolButton()
        self.preview_ut_button.setText("Preview auf UT")
        self.preview_ut_button.clicked.connect(self.set_preview_to_ut)
        toolbar.addWidget(self.preview_ut_button)

        toolbar.addSeparator()
        toolbar.addWidget(QLabel("Preview-Winkel"))
        self.angle_slider = QSlider(Qt.Horizontal)
        self.angle_slider.setFixedWidth(240)
        self.angle_slider.valueChanged.connect(self.set_preview_angle)
        toolbar.addWidget(self.angle_slider)
        self.angle_label = QLabel("180°")
        self.angle_label.setMinimumWidth(58)
        toolbar.addWidget(self.angle_label)

        self.auto_button = QToolButton()
        self.auto_button.setCheckable(True)
        self.auto_button.setText("Y links Auto")
        self.auto_button.toggled.connect(self.toggle_auto_fit)
        toolbar.addWidget(self.auto_button)

        self.right_axis_toggle = QToolButton()
        self.right_axis_toggle.setCheckable(True)
        self.right_axis_toggle.setToolTip("Rechte Y-Achse: Kolbenweg ab UT oder Volumen")
        self.right_axis_toggle.toggled.connect(self.toggle_right_axis_mode)
        toolbar.addWidget(self.right_axis_toggle)

        self.preview_settings_button = QToolButton()
        self.preview_settings_button.setText("Preview-Stil…")
        self.preview_settings_button.clicked.connect(self.open_preview_style_dialog)
        toolbar.addWidget(self.preview_settings_button)

    def _build_statusbar(self) -> None:
        status = QStatusBar(self)
        self.setStatusBar(status)
        self.status_mode = QLabel()
        self.status_units = QLabel()
        self.status_cycle = QLabel()
        self.status_display = QLabel()
        self.status_path = QLabel()
        for label in (self.status_mode, self.status_units, self.status_cycle, self.status_display):
            label.setFrameStyle(QFrame.Panel | QFrame.Sunken)
            label.setContentsMargins(6, 0, 6, 0)
            status.addPermanentWidget(label)
        self.status_path.setFrameStyle(QFrame.Panel | QFrame.Sunken)
        self.status_path.setContentsMargins(6, 0, 6, 0)
        self.status_path.setMinimumWidth(280)
        status.addPermanentWidget(self.status_path, 1)

    def _make_scroll_area(self, widget: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        area.setWidget(widget)
        return area

    def _build_docks(self) -> None:
        self.engine_panel = EngineEditorPanel(self)
        self.engine_panel.setMinimumWidth(360)
        self.engine_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.gas_panel = GasExchangePanel(self)
        self.gas_panel.setMinimumWidth(400)
        self.gas_panel.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.timing_preview = TimingPreviewWidget(self)
        self.timing_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.section_preview = SectionPreviewWidget(self)
        self.section_preview.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.json_preview = QPlainTextEdit()
        self.json_preview.setReadOnly(True)
        self.json_preview.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.json_preview.setMinimumHeight(220)

        self.engine_dock = self._create_dock("Engine", self._make_scroll_area(self.engine_panel))
        self.gas_dock = self._create_dock("Gasexchange", self._make_scroll_area(self.gas_panel))
        self.timing_dock = self._create_dock("Timing preview", self._make_scroll_area(self.timing_preview))
        self.section_dock = self._create_dock("Section preview", self._make_scroll_area(self.section_preview))
        self.json_dock = self._create_dock("JSON preview", self.json_preview)

        self.all_docks = [self.engine_dock, self.gas_dock, self.timing_dock, self.section_dock, self.json_dock]
        self._apply_default_layout()
        for dock in self.all_docks:
            self.view_menu.addAction(dock.toggleViewAction())
        self.apply_json_preview_style()

    def _create_dock(self, title: str, widget: QWidget) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(f"dock_{title.lower().replace(' ', '_')}")
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        dock.setFeatures(
            QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable | QDockWidget.DockWidgetClosable
        )
        dock.setMinimumWidth(240)
        dock.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return dock

    def _populate_style_menu(self) -> None:
        self.style_menu.clear()
        for style_name in sorted(QStyleFactory.keys()):
            action = QAction(style_name, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, name=style_name: self.apply_style(name))
            self.style_action_group.addAction(action)
            self.style_menu.addAction(action)

    def _apply_saved_style(self) -> None:
        style_name = str(self.settings.value("ui/style_name", QApplication.style().objectName()))
        available = {name.lower(): name for name in QStyleFactory.keys()}
        key = style_name.lower()
        if key not in available and available:
            style_name = sorted(available.values())[0]
        elif key in available:
            style_name = available[key]
        self.apply_style(style_name, announce=False)

    def apply_style(self, style_name: str, announce: bool = True) -> None:
        if style_name and style_name in QStyleFactory.keys():
            QApplication.setStyle(QStyleFactory.create(style_name))
            self.settings.setValue("ui/style_name", style_name)
            for action in self.style_action_group.actions():
                action.blockSignals(True)
                action.setChecked(action.text() == style_name)
                action.blockSignals(False)
            self._update_statusbar_fields()
            if announce:
                self.statusBar().showMessage(f"Style gewechselt: {style_name}", 2500)

    def _apply_default_layout(self) -> None:
        for dock in getattr(self, "all_docks", []):
            self.removeDockWidget(dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.engine_dock)
        self.splitDockWidget(self.engine_dock, self.gas_dock, Qt.Vertical)
        self.addDockWidget(Qt.RightDockWidgetArea, self.timing_dock)
        self.splitDockWidget(self.timing_dock, self.section_dock, Qt.Vertical)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.json_dock)

    def _restore_layout(self) -> None:
        geometry = self.settings.value("window/geometry")
        state = self.settings.value("window/state")
        restored = False
        if geometry:
            restored = bool(self.restoreGeometry(geometry))
        if state:
            restored = bool(self.restoreState(state)) or restored
        if not restored:
            self._apply_default_layout()

    def _restore_view_state(self) -> None:
        self._update_preview_slider_range()
        self.preview_angle_deg = clamp(self.preview_angle_deg, *self.current_plot_range())
        self._sync_toolbar_from_state()
        self._update_statusbar_fields()
        self.apply_json_preview_style()
        self.timing_preview.update()
        self.section_preview.update()

    def save_layout_to_settings(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        self.settings.sync()
        self.statusBar().showMessage("Layout gespeichert", 2500)

    def reset_layout(self) -> None:
        self.settings.remove("window/geometry")
        self.settings.remove("window/state")
        self._apply_default_layout()
        self.statusBar().showMessage("Layout zurückgesetzt", 2500)

    def closeEvent(self, event) -> None:
        self.save_layout_to_settings()
        self._save_view_settings()
        self.file_preview_popup.hide()
        super().closeEvent(event)

    def _save_view_settings(self) -> None:
        self.settings.setValue("ui/unit_mode", self.unit_mode)
        self.settings.setValue("ui/display_mode", self.display_mode)
        self.settings.setValue("ui/right_axis_mode", self.right_axis_mode)
        self.settings.setValue("ui/start_from_zero", self.start_plot_from_zero)
        self.settings.setValue("ui/auto_fit_left_axis", self.auto_fit_left_axis)
        self.settings.setValue("ui/preview_angle_deg", float(self.preview_angle_deg))
        self.settings.setValue("ui/manual_left_axis_max", float(self.manual_left_axis_max))
        self.settings.setValue("ui/manual_right_axis_max", float(self.manual_right_axis_max))
        self.settings.setValue("ui/last_cycle_type", self.cycle_type())
        self.settings.setValue("preview/style_json", self.preview_style.to_json())
        self.settings.sync()

    def temperature_model_to_display(self, value_k: float) -> float:
        return value_k - 273.15 if self.unit_mode == "eng" else value_k

    def temperature_display_to_model(self, value_disp: float) -> float:
        return value_disp + 273.15 if self.unit_mode == "eng" else value_disp

    def ensure_defaults(self) -> None:
        self.config_data = merge_dicts(self.default_config(), self.config_data)
        engine = ensure_path(self.config_data, "engine", {})
        if "bore_m" not in engine and "bore" in engine:
            engine["bore_m"] = engine["bore"]
            self.engine_save_aliases["bore_m"] = "bore"
        else:
            self.engine_save_aliases["bore_m"] = "bore_m"
        if "stroke_m" not in engine and "stroke" in engine:
            engine["stroke_m"] = engine["stroke"]
            self.engine_save_aliases["stroke_m"] = "stroke"
        else:
            self.engine_save_aliases["stroke_m"] = "stroke_m"
        if "conrod_m" not in engine and "conrod" in engine:
            engine["conrod_m"] = engine["conrod"]
            self.engine_save_aliases["conrod_m"] = "conrod"
        else:
            self.engine_save_aliases["conrod_m"] = "conrod_m"
        if str(engine.get("cycle_type", "4T")).upper() not in CYCLE_CHOICES:
            engine["cycle_type"] = "4T"
        engine["wall_heat"] = _editor_sanitize_wall_heat_config(engine.get("wall_heat") or self.default_config()["engine"].get("wall_heat") or {})
        if str(deep_get(self.config_data, "gasexchange.mode", "valves")) not in MODE_CHOICES:
            deep_set(self.config_data, "gasexchange.mode", "valves")

        for side in ("intake", "exhaust"):
            self.normalize_valve_side(side)
            for mode_name in ("ports", "slots"):
                self.normalize_window_side(mode_name, side)

    def normalize_valve_side(self, side: str) -> None:
        valves = ensure_path(self.config_data, "gasexchange.valves", {})
        defaults = self.default_config()["gasexchange"]["valves"]
        default_lift_angle_basis = str(defaults.get("lift_angle_basis", "cam") or "cam").lower()
        default_cam_to_crank_ratio = float(defaults.get("cam_to_crank_ratio", 2.0) or 2.0)
        default_effective_lift_threshold_mm = float(defaults.get("effective_lift_threshold_mm", 0.0) or 0.0)

        lift_angle_basis = str(valves.get("lift_angle_basis", default_lift_angle_basis) or default_lift_angle_basis).lower()
        valves["lift_angle_basis"] = lift_angle_basis if lift_angle_basis in {"cam", "crank"} else default_lift_angle_basis
        valves["cam_to_crank_ratio"] = max(float(valves.get("cam_to_crank_ratio", default_cam_to_crank_ratio) or default_cam_to_crank_ratio), 1e-6)
        threshold_mm = valves.get("effective_lift_threshold_mm", default_effective_lift_threshold_mm)
        valves["effective_lift_threshold_mm"] = max(float(threshold_mm or 0.0), 0.0)

        scaling = ensure_path(self.config_data, "gasexchange.valves.scaling", copy.deepcopy(defaults["scaling"]))
        side_scaling = ensure_path(self.config_data, f"gasexchange.valves.scaling.{side}", copy.deepcopy(defaults["scaling"][side]))
        side_scaling["angle_scale"] = max(float(side_scaling.get("angle_scale", defaults["scaling"][side]["angle_scale"]) or 1.0), 0.01)
        side_scaling["lift_scale"] = max(float(side_scaling.get("lift_scale", defaults["scaling"][side]["lift_scale"]) or 1.0), 0.01)
        scaling[side] = side_scaling

        base = ensure_path(self.config_data, f"gasexchange.valves.{side}", {})
        side_defaults = defaults[side]
        side_basis = str(
            base.get("profile_angle_domain", base.get("_profile_angle_domain", valves.get("lift_angle_basis", side_defaults.get("profile_angle_domain", default_lift_angle_basis))))
            or side_defaults.get("profile_angle_domain", default_lift_angle_basis)
        ).lower()
        if side_basis not in {"cam", "crank"}:
            side_basis = str(side_defaults.get("profile_angle_domain", default_lift_angle_basis) or default_lift_angle_basis).lower()
        base["profile_angle_domain"] = side_basis
        base["_profile_angle_domain"] = side_basis

        open_deg = base.get("open_deg", base.get("open"))
        close_deg = base.get("close_deg", base.get("close"))
        center = base.get("center_deg", base.get("center"))
        max_lift = base.get("max_lift_m", base.get("max_lift"))
        span_scaled = max(self.valve_scaled_span_deg(side), 1.0e-9)

        if open_deg is not None:
            open_f = float(open_deg)
        elif close_deg is not None:
            open_f = float(close_deg) - span_scaled
        elif center is not None:
            open_f = float(center) - 0.5 * span_scaled
        else:
            open_f = float(side_defaults["open_deg"])

        lift_file = str(base.get("lift_file", valves.get("lift_file", "")) or "").strip()
        alphak_file = str(base.get("alphak_file", valves.get("alphak_file", "")) or "").strip()

        base["lift_file"] = lift_file
        base["alphak_file"] = alphak_file
        base["open_deg"] = open_f
        base["max_lift_m"] = max(float(side_defaults["max_lift_m"] if max_lift is None else max_lift), 0.0)

    def normalize_window_side(self, mode_name: str, side: str) -> None:
        base_path = f"gasexchange.{mode_name}.{side}"
        base = ensure_path(self.config_data, base_path, {})
        defaults = self.default_config()["gasexchange"][mode_name][side]
        field_aliases = {
            "width_m": ("width_m", "width"),
            "height_m": ("height_m", "height"),
            "offset_from_ut_m": ("offset_from_ut_m", "offset_from_ut"),
            "count": ("count",),
        }
        if mode_name == "slots":
            field_aliases.update({
                "forward_discharge_coefficient": ("forward_discharge_coefficient",),
                "reverse_discharge_coefficient": ("reverse_discharge_coefficient",),
            })
        else:
            field_aliases.update({
                "alphak_file": ("alphak_file",),
            })
        for canonical, aliases in field_aliases.items():
            chosen = None
            for alias in aliases:
                if alias in base:
                    chosen = base[alias]
                    break
            if chosen is None:
                chosen = defaults.get(canonical)
            base[canonical] = chosen

        roof = ensure_path(self.config_data, f"{base_path}.roof", copy.deepcopy(defaults["roof"]))
        roof_type = roof.get("type", base.get("roof_type", defaults["roof"]["type"]))
        roof_len = roof.get("len_m", base.get("roof_len", defaults["roof"]["len_m"]))
        roof_gamma = roof.get("gamma", base.get("roof_gamma", defaults["roof"]["gamma"]))
        roof_angle = roof.get("angle_deg", base.get("roof_angle_deg", defaults["roof"]["angle_deg"]))
        roof["type"] = roof_type if str(roof_type) in ROOF_CHOICES else "none"
        roof["len_m"] = float(roof_len or 0.0)
        roof["gamma"] = float(roof_gamma or 1.0)
        roof["angle_deg"] = float(roof_angle or 0.0)

    def load_json_via_dialog(self) -> None:
        start_dir = str(self.current_path.parent if self.current_path else Path.cwd())
        filename, _ = get_open_file_name(self, "JSON laden", start_dir, "JSON-Dateien (*.json);;Alle Dateien (*.*)")
        if filename:
            self.load_json(Path(filename))

    def load_json(self, path: Path) -> None:
        try:
            with path.open("r", encoding="utf-8") as handle:
                loaded = json.load(handle)
        except Exception as exc:
            show_critical(self, "Laden fehlgeschlagen", str(exc))
            return

        subset = {
            "engine": copy.deepcopy(loaded.get("engine", {})),
            "gasexchange": copy.deepcopy(loaded.get("gasexchange", {})),
        }
        self.config_data = merge_dicts(self.default_config(), subset)
        self.current_path = path
        self.ensure_defaults()
        self.refresh_ui_from_model()
        self.statusBar().showMessage(f"Geladen: {path}", 3500)

    def save_json(self) -> None:
        if self.current_path is None:
            self.save_json_as()
            return
        data = self.serialize_subset()
        try:
            with self.current_path.open("w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
        except Exception as exc:
            show_critical(self, "Speichern fehlgeschlagen", str(exc))
            return
        self.statusBar().showMessage(f"Gespeichert: {self.current_path}", 3000)
        self._update_statusbar_fields()

    def save_json_as(self) -> None:
        start_dir = str(self.current_path.parent if self.current_path else Path.cwd())
        filename, _ = get_save_file_name(self, "JSON speichern unter", start_dir, "JSON-Dateien (*.json)")
        if not filename:
            return
        path = Path(filename)
        if path.suffix.lower() != ".json":
            path = path.with_suffix(".json")
        self.current_path = path
        self.save_json()
        self.statusBar().showMessage(f"Gespeichert unter: {self.current_path}", 3000)

    def serialize_subset(self) -> dict[str, Any]:
        engine_internal = copy.deepcopy(self.config_data.get("engine", {}))
        gasexchange = copy.deepcopy(self.config_data.get("gasexchange", {}))
        engine_out: dict[str, Any] = {}
        for key, value in engine_internal.items():
            if key in {"bore_m", "stroke_m", "conrod_m"}:
                out_key = self.engine_save_aliases.get(key, key)
                engine_out[out_key] = value
            else:
                engine_out[key] = value
        return {"engine": engine_out, "gasexchange": gasexchange}

    def cycle_type(self) -> str:
        cycle = str(deep_get(self.config_data, "engine.cycle_type", "4T") or "4T").upper()
        return cycle if cycle in CYCLE_CHOICES else "4T"

    def active_gasexchange_mode(self) -> str:
        mode = str(deep_get(self.config_data, "gasexchange.mode", "valves") or "valves")
        return mode if mode in MODE_CHOICES else "valves"

    def engine_value(self, key: str) -> float:
        return float(deep_get(self.config_data, f"engine.{key}", self.default_config()["engine"].get(key, 0.0)) or 0.0)


    def current_plot_range(self) -> tuple[float, float]:
        return plot_x_range(self.cycle_type(), self.start_plot_from_zero)

    def x_grid_values(self) -> list[float]:
        x_min, x_max = self.current_plot_range()
        step = max(float(self.preview_style.x_grid_step_deg), 1.0)
        start = math.floor(x_min / step) * step
        values = []
        x = start
        while x <= x_max + 1e-9:
            if x >= x_min - 1e-9:
                values.append(x)
            x += step
        return values

    def x_tick_values(self) -> list[float]:
        x_min, x_max = self.current_plot_range()
        step = max(float(self.preview_style.x_major_grid_step_deg), max(float(self.preview_style.x_grid_step_deg), 1.0))
        start = math.floor(x_min / step) * step
        values = []
        x = start
        while x <= x_max + 1e-9:
            if x >= x_min - 1e-9:
                values.append(x)
            x += step
        return values

    def is_major_x_grid_value(self, value_deg: float) -> bool:
        major_step = max(float(self.preview_style.x_major_grid_step_deg), max(float(self.preview_style.x_grid_step_deg), 1.0))
        quotient = value_deg / major_step
        return abs(quotient - round(quotient)) <= 1e-6

    def plot_length_unit(self) -> str:
        return "mm" if self.unit_mode == "eng" else "m"

    def plot_area_unit(self) -> str:
        return "cm²" if self.unit_mode == "eng" else "m²"

    def plot_volume_unit(self) -> str:
        return "cm³" if self.unit_mode == "eng" else "m³"

    def plot_length_from_m(self, value_m: float) -> float:
        return value_m * (1000.0 if self.unit_mode == "eng" else 1.0)

    def plot_area_from_m2(self, value_m2: float) -> float:
        return value_m2 * (1.0e4 if self.unit_mode == "eng" else 1.0)

    def plot_volume_from_m3(self, value_m3: float) -> float:
        return value_m3 * (1.0e6 if self.unit_mode == "eng" else 1.0)

    def estimated_clearance_height(self) -> float:
        bore = self.engine_value("bore_m")
        stroke = self.engine_value("stroke_m")
        compression_ratio = self.engine_value("compression_ratio")
        area = math.pi * bore * bore / 4.0
        swept = area * stroke
        clearance_volume = swept / max(compression_ratio - 1.0, 0.1)
        return clearance_volume / max(area, 1e-12)

    def valve_scaling(self, side: str) -> tuple[float, float]:
        angle_scale = max(float(deep_get(self.config_data, f"gasexchange.valves.scaling.{side}.angle_scale", 1.0) or 1.0), 0.01)
        lift_scale = max(float(deep_get(self.config_data, f"gasexchange.valves.scaling.{side}.lift_scale", 1.0) or 1.0), 0.01)
        return angle_scale, lift_scale

    def valve_base_span_deg(self, side: str) -> float:
        default_span = 240.0 if side == "intake" else 230.0
        return max(float(deep_get(self.config_data, f"gasexchange.valves.{side}._base_profile_span_deg", default_span) or default_span), 1.0e-9)

    def valve_scaled_span_deg(self, side: str) -> float:
        angle_scale, _lift_scale = self.valve_scaling(side)
        return max(self.valve_base_span_deg(side) * angle_scale, 1.0e-9)

    def valve_open_deg(self, side: str) -> float:
        default_open = 350.0 if side == "intake" else 135.0
        return float(deep_get(self.config_data, f"gasexchange.valves.{side}.open_deg", default_open) or default_open)

    def valve_close_deg(self, side: str) -> float:
        return self.valve_open_deg(side) + self.valve_scaled_span_deg(side)

    def valve_center_deg(self, side: str) -> float:
        return self.valve_open_deg(side) + 0.5 * self.valve_scaled_span_deg(side)

    def valve_timing_value(self, side: str, mode: str) -> float:
        mode_name = str(mode or "open").strip().lower()
        if mode_name == "close":
            return self.valve_close_deg(side)
        if mode_name == "center":
            return self.valve_center_deg(side)
        return self.valve_open_deg(side)

    def set_valve_open_from_display_value(self, side: str, mode: str, value_deg: float) -> None:
        mode_name = str(mode or "open").strip().lower()
        span_deg = self.valve_scaled_span_deg(side)
        target_value = float(value_deg)
        if mode_name == "close":
            open_deg = target_value - span_deg
        elif mode_name == "center":
            open_deg = target_value - 0.5 * span_deg
        else:
            open_deg = target_value
        deep_set(self.config_data, f"gasexchange.valves.{side}.open_deg", open_deg)

    def effective_lift_threshold_m(self) -> float:
        threshold_mm = max(float(deep_get(self.config_data, "gasexchange.valves.effective_lift_threshold_mm", 0.0) or 0.0), 0.0)
        return threshold_mm * 1.0e-3

    def valve_lift_angle_basis(self, side: str | None = None) -> str:
        if side:
            side_basis = str(
                deep_get(self.config_data, f"gasexchange.valves.{side}.profile_angle_domain", "")
                or deep_get(self.config_data, f"gasexchange.valves.{side}._profile_angle_domain", "")
                or ""
            ).strip().lower()
            if side_basis in {"cam", "crank"}:
                return side_basis
        basis = str(deep_get(self.config_data, "gasexchange.valves.lift_angle_basis", "cam") or "cam").strip().lower()
        return basis if basis in {"cam", "crank"} else "cam"

    def valve_lift_basis_summary(self) -> str:
        intake_basis = self.valve_lift_angle_basis("intake").upper()
        exhaust_basis = self.valve_lift_angle_basis("exhaust").upper()
        return f"IN={intake_basis} | EX={exhaust_basis}"

    def apply_valve_scaling(self, side: str) -> None:
        self.refresh_valve_profile_metadata()
        current_max_lift = max(float(deep_get(self.config_data, f"gasexchange.valves.{side}.max_lift_m", 0.0) or 0.0), 0.0)
        base_max_lift = max(float(deep_get(self.config_data, f"gasexchange.valves.{side}._base_profile_max_lift_m", current_max_lift) or current_max_lift), 0.0)
        _angle_scale, lift_scale = self.valve_scaling(side)
        max_lift = max(base_max_lift * lift_scale, 0.0)
        deep_set(self.config_data, f"gasexchange.valves.{side}.max_lift_m", max_lift)

    def cam_to_crank_ratio(self) -> float:
        return max(float(deep_get(self.config_data, "gasexchange.valves.cam_to_crank_ratio", 2.0) or 2.0), 0.01)

    def resolve_project_path(self, path_text: str | Path) -> Path:
        raw = Path(str(path_text or "")).expanduser()
        if raw.is_absolute():
            return raw
        base = self.current_path.parent if self.current_path else Path.cwd()
        return (base / raw).resolve()

    def load_lift_profile_pairs(self, path_text: str, side: str | None = None) -> list[tuple[float, float]]:
        path_text = str(path_text or "").strip()
        if not path_text:
            return []
        basis = self.valve_lift_angle_basis(side)
        ratio = self.cam_to_crank_ratio()
        cache_key = (path_text, ratio, basis)
        if cache_key in self._lift_profile_cache:
            return list(self._lift_profile_cache[cache_key])
        try:
            path = self.resolve_project_path(path_text)
            raw_pairs = _editor_load_csv_pairs(path, table_kind="valve_lift")
        except Exception:
            raw_pairs = []
        factor = ratio if basis == "cam" else 1.0
        converted = [(float(x) * factor, max(0.0, float(y))) for x, y in raw_pairs]
        converted.sort(key=lambda item: item[0])
        self._lift_profile_cache[cache_key] = converted
        return list(converted)

    def invalidate_lift_profile_cache(self, path_text: str = "") -> None:
        key_text = str(path_text or "").strip()
        if not key_text:
            self._lift_profile_cache.clear()
            return
        self._lift_profile_cache = {k: v for k, v in self._lift_profile_cache.items() if k[0] != key_text}

    def refresh_valve_profile_metadata(self) -> None:
        for side in ("intake", "exhaust"):
            lift_path = str(deep_get(self.config_data, f"gasexchange.valves.{side}.lift_file", "") or "").strip()
            pairs = self.load_lift_profile_pairs(lift_path, side)
            if not pairs:
                continue
            xs = [p[0] for p in pairs]
            ys = [max(0.0, p[1]) for p in pairs]
            active = [i for i, y in enumerate(ys) if y > 1.0e-12]
            if active:
                base_duration = max(xs[active[-1]] - xs[active[0]], 1.0e-9)
            else:
                base_duration = max(xs[-1] - xs[0], 1.0)
            base_max_lift = max(ys) if ys else 0.0
            deep_set(self.config_data, f"gasexchange.valves.{side}._base_profile_span_deg", float(base_duration))
            deep_set(self.config_data, f"gasexchange.valves.{side}._base_profile_max_lift_m", float(base_max_lift))
            deep_set(self.config_data, f"gasexchange.valves.{side}._profile_angle_domain", self.valve_lift_angle_basis(side))

    def _sample_linear_pairs(self, pairs: list[tuple[float, float]], x_value: float) -> float:
        if not pairs:
            return 0.0
        if x_value < pairs[0][0] or x_value > pairs[-1][0]:
            return 0.0
        for idx in range(1, len(pairs)):
            x0, y0 = pairs[idx - 1]
            x1, y1 = pairs[idx]
            if x_value <= x1:
                if abs(x1 - x0) <= 1.0e-12:
                    return max(0.0, y1)
                frac = (x_value - x0) / (x1 - x0)
                return max(0.0, y0 + frac * (y1 - y0))
        return max(0.0, pairs[-1][1])

    def compute_valve_lift(self, side: str, theta_deg: float) -> float:
        open_deg = self.valve_open_deg(side)
        center = self.valve_center_deg(side)
        span_deg = self.valve_scaled_span_deg(side)
        max_lift = float(deep_get(self.config_data, f"gasexchange.valves.{side}.max_lift_m", 0.0) or 0.0)
        effective_lift = max(max_lift, 0.0)

        lift_path = str(
            deep_get(self.config_data, f"gasexchange.valves.{side}.lift_file", "")
            or deep_get(self.config_data, f"gasexchange.valves.{side}._lift_file", "")
            or ""
        ).strip()
        pairs = self.load_lift_profile_pairs(lift_path, side)
        if len(pairs) >= 2 and span_deg > 1.0e-12:
            x_min = pairs[0][0]
            x_max = pairs[-1][0]
            event_open = center - 0.5 * span_deg
            scaled_theta = x_min + ((theta_deg - event_open) / span_deg) * (x_max - x_min)
            raw_lift = self._sample_linear_pairs(pairs, scaled_theta)
            raw_max = max((p[1] for p in pairs), default=0.0)
            if raw_max > 1.0e-12:
                return max(raw_lift * (effective_lift / raw_max), 0.0)
        return valve_lift_profile(theta_deg, center, span_deg, effective_lift, self.cycle_type())

    def compute_valve_effective_area(self, side: str, theta_deg: float) -> float:
        lift = self.compute_valve_lift(side, theta_deg)
        lash_m = max(float(deep_get(self.config_data, f"gasexchange.valves.{side}._lash_m", 0.0) or 0.0), 0.0)
        threshold = self.effective_lift_threshold_m()
        effective_lift = max(lift - lash_m - threshold, 0.0)
        bore = max(self.engine_value("bore_m"), 0.0)
        bore_area = 0.25 * math.pi * bore * bore
        alpha_k = self.preview_area_coefficient(side, theta_deg, "valves")
        if effective_lift <= 1.0e-18 or bore_area <= 1.0e-18:
            return 0.0
        return max(alpha_k * bore_area, 0.0)

    def window_base_path(self, side: str, mode: str | None = None) -> str:
        mode_name = mode or self.active_gasexchange_mode()
        if mode_name not in {"ports", "slots"}:
            mode_name = "slots"
        return f"gasexchange.{mode_name}.{side}"

    def compute_window_open_height(self, side: str, theta_deg: float, mode: str | None = None) -> float:
        mode_name = mode or self.active_gasexchange_mode()
        if mode_name == "valves":
            return self.compute_valve_lift(side, theta_deg)
        base = self.window_base_path(side, mode_name)
        stroke = self.engine_value("stroke_m")
        conrod = self.engine_value("conrod_m")
        piston_from_ut = piston_distance_from_ut(stroke, conrod, theta_deg)
        offset = float(deep_get(self.config_data, f"{base}.offset_from_ut_m", 0.0) or 0.0)
        height = float(deep_get(self.config_data, f"{base}.height_m", 0.0) or 0.0)
        raw = clamp(height - (piston_from_ut - offset), 0.0, height)
        return raw * 0.92 if mode_name == "ports" else raw

    def compute_roof_factor(self, base: str, open_height_m: float) -> float:
        roof_type = str(deep_get(self.config_data, f"{base}.roof.type", "none") or "none")
        roof_len = float(deep_get(self.config_data, f"{base}.roof.len_m", 0.0) or 0.0)
        roof_gamma = float(deep_get(self.config_data, f"{base}.roof.gamma", 1.0) or 1.0)
        roof_angle = float(deep_get(self.config_data, f"{base}.roof.angle_deg", 0.0) or 0.0)
        if roof_type == "none":
            return 1.0
        if roof_type == "linear":
            return 1.0 + clamp(roof_len / max(open_height_m + 1e-12, 1e-12), 0.0, 0.35)
        if roof_type == "cos":
            return 1.0 + 0.18 * (1.0 - math.cos(clamp(roof_len * 180.0, 0.0, math.pi)))
        if roof_type == "factor":
            return 1.0 + 0.1 * max(roof_gamma, 0.0)
        if roof_type == "angle":
            return 1.0 + 0.0025 * abs(roof_angle)
        return 1.0

    def _resolve_data_path(self, path_text: str) -> Path:
        path = Path(path_text)
        if path.is_absolute() or self.current_path is None:
            return path
        return (self.current_path.parent / path).resolve()

    def _load_profile_preview_data(self, path_text: str) -> dict[str, Any] | None:
        if not path_text:
            return None
        resolved = self._resolve_data_path(path_text)
        if not resolved.exists() or not resolved.is_file():
            return None
        mtime = int(resolved.stat().st_mtime_ns)
        cache_key = (str(resolved), mtime)
        cached = self.file_preview_cache.get(cache_key)
        if cached is None:
            cached = parse_numeric_text_preview(resolved)
            self.file_preview_cache[cache_key] = cached
        if cached.get("error"):
            return None
        x_vals = cached.get("x") or []
        y_vals = cached.get("y") or []
        if not y_vals:
            return None
        return cached

    def _interpolate_profile(self, path_text: str, theta_deg: float, fallback: float = 1.0) -> float:
        data = self._load_profile_preview_data(path_text)
        if not data:
            return fallback
        x_vals = [float(v) for v in (data.get("x") or [])]
        y_vals = [float(v) for v in (data.get("y") or [])]
        if not y_vals:
            return fallback
        if not x_vals:
            return max(float(y_vals[0]), 0.0)
        pairs = sorted(zip(x_vals, y_vals), key=lambda item: item[0])
        xs = [p[0] for p in pairs]
        ys = [p[1] for p in pairs]
        if len(xs) == 1:
            return max(float(ys[0]), 0.0)
        x = float(theta_deg)
        if x <= xs[0]:
            return max(float(ys[0]), 0.0)
        if x >= xs[-1]:
            return max(float(ys[-1]), 0.0)
        for idx in range(1, len(xs)):
            if x <= xs[idx]:
                x0, y0 = xs[idx - 1], ys[idx - 1]
                x1, y1 = xs[idx], ys[idx]
                if abs(x1 - x0) < 1e-12:
                    return max(float(y1), 0.0)
                frac = (x - x0) / (x1 - x0)
                return max(float(y0 + frac * (y1 - y0)), 0.0)
        return max(float(ys[-1]), 0.0)

    def load_alpha_k_table(self, path_text: str) -> list[tuple[float, float, float]]:
        path_text = str(path_text or "").strip()
        if not path_text:
            return []
        if path_text in self._alpha_k_profile_cache:
            return list(self._alpha_k_profile_cache[path_text])
        try:
            path = self.resolve_project_path(path_text)
            rows = _editor_load_csv_table(path, 3, table_kind="valve_alpha")
        except Exception:
            rows = []
        converted = [(float(row[0]), float(row[1]), float(row[2])) for row in rows if len(row) >= 3]
        converted.sort(key=lambda item: item[0])
        self._alpha_k_profile_cache[path_text] = converted
        return list(converted)

    def invalidate_alpha_k_profile_cache(self, path_text: str = "") -> None:
        key_text = str(path_text or "").strip()
        if not key_text:
            self._alpha_k_profile_cache.clear()
            return
        self._alpha_k_profile_cache.pop(key_text, None)

    def _interpolate_alpha_k_value(self, path_text: str, lift_m: float, column: int = 1, fallback: float = 0.0) -> float:
        rows = self.load_alpha_k_table(path_text)
        if not rows:
            return fallback
        pairs: list[tuple[float, float]] = []
        for row in rows:
            if len(row) <= column:
                continue
            pairs.append((float(row[0]), float(row[column])))
        if not pairs:
            return fallback
        return max(self._sample_linear_pairs(pairs, float(lift_m)), 0.0)

    def preview_area_coefficient(self, side: str, theta_deg: float, mode: str | None = None) -> float:
        mode_name = mode or self.active_gasexchange_mode()
        if mode_name == "valves":
            lift_m = self.compute_valve_lift(side, theta_deg)
            lash_m = max(float(deep_get(self.config_data, f"gasexchange.valves.{side}._lash_m", 0.0) or 0.0), 0.0)
            effective_lift = max(lift_m - lash_m, 0.0)
            path_text = str(deep_get(self.config_data, f"gasexchange.valves.{side}.alpha_k_file", "") or deep_get(self.config_data, f"gasexchange.valves.{side}.alphak_file", "") or deep_get(self.config_data, f"gasexchange.valves.{side}._alpha_k_file", "") or "")
            return self._interpolate_alpha_k_value(path_text, effective_lift, column=1, fallback=0.0)
        if mode_name == "ports":
            side_path = str(deep_get(self.config_data, f"gasexchange.ports.{side}.alpha_k_file", "") or deep_get(self.config_data, f"gasexchange.ports.{side}.alphak_file", "") or "")
            shared_path = str(deep_get(self.config_data, "gasexchange.ports.alpha_k_file", "") or deep_get(self.config_data, "gasexchange.ports.alphak_file", "") or "")
            return self._interpolate_profile(side_path or shared_path, theta_deg, fallback=1.0)
        if mode_name == "slots":
            side_coeff = deep_get(self.config_data, f"gasexchange.slots.{side}.forward_discharge_coefficient", None)
            if side_coeff is None:
                side_coeff = deep_get(self.config_data, "gasexchange.slots.forward_discharge_coefficient", 1.0)
            try:
                return max(float(side_coeff), 0.0)
            except Exception:
                return 1.0
        return 1.0

    def compute_window_effective_area(self, side: str, theta_deg: float, mode: str | None = None) -> float:
        mode_name = mode or self.active_gasexchange_mode()
        if mode_name == "valves":
            return self.compute_valve_effective_area(side, theta_deg)
        base = self.window_base_path(side, mode_name)
        width = float(deep_get(self.config_data, f"{base}.width_m", 0.0) or 0.0)
        count = int(deep_get(self.config_data, f"{base}.count", 0) or 0)
        open_height = self.compute_window_open_height(side, theta_deg, mode_name)
        roof_factor = self.compute_roof_factor(base, open_height)
        mode_factor = 0.96 if mode_name == "ports" else 1.0
        coeff = self.preview_area_coefficient(side, theta_deg, mode_name)
        return max(width, 0.0) * max(open_height, 0.0) * max(count, 0) * roof_factor * mode_factor * coeff

    def preview_pair(self, theta_deg: float) -> tuple[float, float]:
        mode = self.active_gasexchange_mode()
        if self.display_mode == AREA_MODE:
            intake = self.plot_area_from_m2(self.compute_window_effective_area("intake", theta_deg, mode))
            exhaust = self.plot_area_from_m2(self.compute_window_effective_area("exhaust", theta_deg, mode))
            return intake, exhaust
        if mode == "valves":
            intake_l = self.plot_length_from_m(self.compute_valve_lift("intake", theta_deg))
            exhaust_l = self.plot_length_from_m(self.compute_valve_lift("exhaust", theta_deg))
            return intake_l, exhaust_l
        intake_h = self.plot_length_from_m(self.compute_window_open_height("intake", theta_deg, mode))
        exhaust_h = self.plot_length_from_m(self.compute_window_open_height("exhaust", theta_deg, mode))
        return intake_h, exhaust_h

    def active_display_mode_title(self) -> str:
        if self.display_mode == AREA_MODE:
            return DISPLAY_MODE_LABELS[AREA_MODE]
        mode = self.active_gasexchange_mode()
        if mode == "valves":
            return DISPLAY_MODE_LABELS[LIFT_MODE]
        if mode == "ports":
            return "Port-Höhe"
        return DISPLAY_MODE_LABELS[HEIGHT_MODE]

    def active_left_axis_title(self) -> str:
        if self.display_mode == AREA_MODE:
            return "Öffnungsfläche"
        mode = self.active_gasexchange_mode()
        if mode == "valves":
            return "Ventilhub"
        if mode == "ports":
            return "Port-Höhe"
        return "Slot-Höhe"

    def active_left_axis_unit(self) -> str:
        return self.plot_area_unit() if self.display_mode == AREA_MODE else self.plot_length_unit()

    def active_right_axis_title(self) -> str:
        return RIGHT_AXIS_MODE_LABELS.get(self.right_axis_mode, RIGHT_AXIS_MODE_LABELS[RIGHT_AXIS_PISTON_MODE])

    def active_right_axis_unit(self) -> str:
        return self.plot_volume_unit() if self.right_axis_mode == RIGHT_AXIS_VOLUME_MODE else self.plot_length_unit()

    def active_right_axis_legend_label(self) -> str:
        return "Volumen" if self.right_axis_mode == RIGHT_AXIS_VOLUME_MODE else "Kolbenweg"

    def preview_right_axis_value(self, bore_m: float, stroke_m: float, conrod_m: float, compression_ratio: float, theta_deg: float) -> float:
        if self.right_axis_mode == RIGHT_AXIS_VOLUME_MODE:
            return self.plot_volume_from_m3(cylinder_volume_m3(bore_m, stroke_m, conrod_m, compression_ratio, theta_deg))
        return self.plot_length_from_m(piston_distance_from_ut(stroke_m, conrod_m, theta_deg))

    def window_section_geometry(self, side: str, theta_deg: float, mode: str) -> dict[str, Any]:
        base = self.window_base_path(side, mode)
        return {
            "width_m": float(deep_get(self.config_data, f"{base}.width_m", 0.0) or 0.0),
            "height_m": float(deep_get(self.config_data, f"{base}.height_m", 0.0) or 0.0),
            "open_height_m": self.compute_window_open_height(side, theta_deg, mode),
            "offset_m": float(deep_get(self.config_data, f"{base}.offset_from_ut_m", 0.0) or 0.0),
            "count": int(deep_get(self.config_data, f"{base}.count", 1) or 1),
            "roof": {
                "type": str(deep_get(self.config_data, f"{base}.roof.type", "none") or "none"),
                "len_px": max(0.0, float(deep_get(self.config_data, f"{base}.roof.len_m", 0.0) or 0.0) * 6000.0),
                "gamma": float(deep_get(self.config_data, f"{base}.roof.gamma", 1.0) or 1.0),
                "angle_deg": float(deep_get(self.config_data, f"{base}.roof.angle_deg", 0.0) or 0.0),
            },
        }

    def _calculate_left_axis_auto_values(self) -> tuple[float, float, float]:
        x_min, x_max = self.current_plot_range()
        theta = float(x_min)
        step_deg = 2.0
        values: list[float] = []
        while theta <= x_max + 1e-9:
            left_in, left_ex = self.preview_pair(normalize_theta(theta, self.cycle_type()))
            values.append(float(left_in))
            values.append(float(left_ex))
            theta += step_deg
        data_max = max(values) if values else 0.0
        axis_min = 0.0
        axis_max = nice_axis_max(max(data_max * 1.12, axis_min + 1e-12))
        ticks = nice_ticks(axis_max, 4)
        axis_step = max((ticks[1] - ticks[0]) if len(ticks) >= 2 else axis_max / 4.0, 1e-9)
        return axis_min, axis_max, axis_step

    def _apply_auto_left_axis_for_current_display(self) -> None:
        axis_min, axis_max, axis_step = self._calculate_left_axis_auto_values()
        self.preview_style.y_axis_min = axis_min
        self.preview_style.y_axis_max = axis_max
        self.preview_style.y_axis_step = axis_step
        self.manual_left_axis_max = axis_max
        if hasattr(self, "preview_style_dialog") and self.preview_style_dialog is not None:
            self.preview_style_dialog.set_style(self.preview_style)

    def refresh_ui_from_model(self) -> None:
        self.loading_ui = True
        try:
            self.ensure_defaults()
            for bindable in self.bindables:
                if hasattr(bindable, "refresh_from_model"):
                    bindable.refresh_from_model()
            self.gas_panel.sync_tabs()
            self._sync_toolbar_from_state()
            self.update_json_preview()
            self._update_statusbar_fields()
            self._update_window_title()
        finally:
            self.loading_ui = False
        self.timing_preview.update()
        self.section_preview.update()

    def on_data_changed(self, reason: str = "") -> None:
        if self.loading_ui:
            return
        if reason == "engine.cycle_type":
            self._update_preview_slider_range()
            self._apply_auto_left_axis_for_current_display()
        elif reason == "gasexchange.mode":
            self.gas_panel.sync_tabs()
            self._apply_auto_left_axis_for_current_display()

        affected_side: str | None = None
        if reason.startswith("gasexchange.valves.intake.") or reason.startswith("gasexchange.valves.scaling.intake."):
            affected_side = "intake"
        elif reason.startswith("gasexchange.valves.exhaust.") or reason.startswith("gasexchange.valves.scaling.exhaust."):
            affected_side = "exhaust"

        if (
            reason.startswith("gasexchange.valves.intake.lift_file")
            or reason.startswith("gasexchange.valves.exhaust.lift_file")
            or reason.startswith("gasexchange.valves.intake._lift_file")
            or reason.startswith("gasexchange.valves.exhaust._lift_file")
            or reason.startswith("gasexchange.valves.intake.profile_angle_domain")
            or reason.startswith("gasexchange.valves.exhaust.profile_angle_domain")
            or reason in {"gasexchange.valves.cam_to_crank_ratio", "gasexchange.valves.lift_angle_basis"}
        ):
            self.invalidate_lift_profile_cache()
            self.refresh_valve_profile_metadata()
            if affected_side is not None:
                self.apply_valve_scaling(affected_side)
        elif reason.startswith("gasexchange.valves.scaling."):
            if affected_side is not None:
                self.apply_valve_scaling(affected_side)
        self.ensure_defaults()
        self.refresh_ui_from_model()

    def update_json_preview(self) -> None:
        self.json_preview.setPlainText(json.dumps(self.serialize_subset(), indent=2, ensure_ascii=False))

    def apply_json_preview_style(self) -> None:
        font = QFont(self.preview_style.json_font_family, self.preview_style.json_font_size)
        font.setStyleHint(QFont.Monospace)
        self.json_preview.setFont(font)
        self.json_preview.setStyleSheet(
            "QPlainTextEdit {"
            f"background-color: {self.preview_style.json_background_color};"
            f"color: {self.preview_style.json_text_color};"
            "selection-background-color: #3b6ea8;"
            "}"
        )

    def _sync_toolbar_from_state(self) -> None:
        self.unit_toggle.blockSignals(True)
        self.unit_toggle.setChecked(self.unit_mode == "eng")
        self.unit_toggle.setText("Engineering" if self.unit_mode == "eng" else "SI")
        self.unit_toggle.blockSignals(False)

        self.cycle_toggle.blockSignals(True)
        is_2t = self.cycle_type() == "2T"
        self.cycle_toggle.setChecked(is_2t)
        self.cycle_toggle.setText("2T" if is_2t else "4T")
        self.cycle_toggle.blockSignals(False)

        self.zero_toggle.blockSignals(True)
        self.zero_toggle.setChecked(self.start_plot_from_zero)
        self.zero_toggle.blockSignals(False)

        self.display_mode_combo.blockSignals(True)
        index = self.display_mode_combo.findData(self.display_mode)
        if index >= 0:
            self.display_mode_combo.setCurrentIndex(index)
        self.display_mode_combo.blockSignals(False)

        self.auto_button.blockSignals(True)
        self.auto_button.setChecked(self.auto_fit_left_axis)
        self.auto_button.blockSignals(False)

        self.right_axis_toggle.blockSignals(True)
        right_axis_is_volume = self.right_axis_mode == RIGHT_AXIS_VOLUME_MODE
        self.right_axis_toggle.setChecked(right_axis_is_volume)
        self.right_axis_toggle.setText("Rechts: Volumen" if right_axis_is_volume else "Rechts: Kolbenweg")
        self.right_axis_toggle.blockSignals(False)

        self._update_preview_slider_range()
        self.angle_label.setText(f"{compact_number(self.preview_angle_deg)}°")

    def _update_preview_slider_range(self) -> None:
        x_min, x_max = self.current_plot_range()
        clamped = clamp(self.preview_angle_deg, x_min, x_max)
        self.angle_slider.blockSignals(True)
        self.angle_slider.setRange(int(round(x_min)), int(round(x_max)))
        self.angle_slider.setValue(int(round(clamped)))
        self.angle_slider.blockSignals(False)
        self.preview_angle_deg = clamped
        self.angle_label.setText(f"{compact_number(clamped)}°")

    def _update_statusbar_fields(self) -> None:
        self.status_mode.setText(f"Mode: {self.active_gasexchange_mode()}")
        self.status_units.setText(f"Units: {'Engineering' if self.unit_mode == 'eng' else 'SI'}")
        self.status_cycle.setText(f"Cycle: {self.cycle_type()}")
        self.status_display.setText(f"Anzeige: {self.active_display_mode_title()}")
        path_text = str(self.current_path) if self.current_path else "neu / unsaved"
        self.status_path.setText(f"Datei: {elide_path_middle(path_text, 90)}")
        self.status_path.setToolTip(path_text)

    def _update_window_title(self) -> None:
        suffix = self.current_path.name if self.current_path else "unsaved"
        self.setWindowTitle(f"EngineGasExchangeEditor – {suffix}")

    def toggle_unit_mode(self, checked: bool) -> None:
        self.unit_mode = "eng" if checked else "si"
        self._save_view_settings()
        self.refresh_ui_from_model()
        self.statusBar().showMessage(f"Einheitenmodus: {'Engineering' if checked else 'SI'}", 2200)

    def toggle_cycle_toolbar(self, checked: bool) -> None:
        deep_set(self.config_data, "engine.cycle_type", "2T" if checked else "4T")
        self.last_cycle_type = "2T" if checked else "4T"
        self._update_preview_slider_range()
        self._save_view_settings()
        self.refresh_ui_from_model()
        self.statusBar().showMessage(f"Cycle-Type geändert: {'2T' if checked else '4T'}", 2200)

    def toggle_zero_start(self, checked: bool) -> None:
        self.start_plot_from_zero = checked
        self._update_preview_slider_range()
        self._save_view_settings()
        self.refresh_ui_from_model()

    def change_display_mode_from_toolbar(self, index: int) -> None:
        data = self.display_mode_combo.itemData(index)
        if data in DISPLAY_MODE_LABELS:
            self.display_mode = str(data)
            self._apply_auto_left_axis_for_current_display()
            self._save_view_settings()
            self.refresh_ui_from_model()
            self.statusBar().showMessage(f"Anzeige-Modus: {DISPLAY_MODE_LABELS[self.display_mode]}", 2200)

    def set_preview_angle(self, value: int) -> None:
        self.preview_angle_deg = float(value)
        self.angle_label.setText(f"{compact_number(self.preview_angle_deg)}°")
        self._save_view_settings()
        self.timing_preview.update()
        self.section_preview.update()

    def set_preview_to_ut(self) -> None:
        self.preview_angle_deg = clamp(180.0, *self.current_plot_range())
        self.angle_slider.blockSignals(True)
        self.angle_slider.setValue(int(round(self.preview_angle_deg)))
        self.angle_slider.blockSignals(False)
        self.angle_label.setText(f"{compact_number(self.preview_angle_deg)}°")
        self._save_view_settings()
        self.timing_preview.update()
        self.section_preview.update()
        self.statusBar().showMessage("Preview auf UT gesetzt", 2200)

    def toggle_auto_fit(self, checked: bool) -> None:
        self.auto_fit_left_axis = checked
        self._save_view_settings()
        self.timing_preview.update()

    def toggle_right_axis_mode(self, checked: bool) -> None:
        self.right_axis_mode = RIGHT_AXIS_VOLUME_MODE if checked else RIGHT_AXIS_PISTON_MODE
        self._save_view_settings()
        self.refresh_ui_from_model()
        self.statusBar().showMessage(f"Rechte Y-Achse: {self.active_right_axis_title()}", 2200)

    def request_file_preview(self, anchor: QWidget, path_text: str) -> None:
        path_text = str(path_text or "").strip()
        if not path_text:
            self.hide_file_preview_later()
            return
        self._hide_preview_timer.stop()
        self._pending_preview_anchor = anchor
        self._pending_preview_path = path_text
        self._file_preview_timer.start(220)

    def hide_file_preview_later(self) -> None:
        self._file_preview_timer.stop()
        self._hide_preview_timer.start(280)

    def invalidate_file_preview_cache(self, path_text: str) -> None:
        if not path_text:
            return
        dead_keys = [key for key in self.file_preview_cache if key[0] == path_text]
        for key in dead_keys:
            self.file_preview_cache.pop(key, None)
        self.invalidate_alpha_k_profile_cache(path_text)

    def _show_pending_file_preview(self) -> None:
        path_text = self._pending_preview_path
        anchor = self._pending_preview_anchor
        if not path_text or anchor is None:
            self.file_preview_popup.hide()
            return
        try:
            if not anchor.isVisible():
                self.file_preview_popup.hide()
                return
        except RuntimeError:
            self.file_preview_popup.hide()
            return
        except Exception:
            self.file_preview_popup.hide()
            return
        path = Path(path_text)
        mtime = int(path.stat().st_mtime_ns) if path.exists() else -1
        cache_key = (path_text, mtime)
        if cache_key in self.file_preview_cache:
            self.file_preview_popup.apply_preview(self.file_preview_cache[cache_key], self.preview_style)
            self.file_preview_popup.show_near(anchor)
            return
        self._preview_request_token += 1
        token = self._preview_request_token
        self._active_preview_token = token
        task = FilePreviewTask(token, path_text)
        task.signals.loaded.connect(self._on_file_preview_loaded)
        self.thread_pool.start(task)

    def _on_file_preview_loaded(self, token: int, path_text: str, result: dict[str, Any]) -> None:
        if token != self._active_preview_token:
            return
        path = Path(path_text)
        mtime = int(path.stat().st_mtime_ns) if path.exists() else -1
        self.file_preview_cache[(path_text, mtime)] = result
        if self._pending_preview_anchor is not None:
            self.file_preview_popup.apply_preview(result, self.preview_style)
            self.file_preview_popup.show_near(self._pending_preview_anchor)

    def open_preview_style_dialog(self) -> None:
        if not hasattr(self, "preview_style_dialog") or self.preview_style_dialog is None:
            self.preview_style_dialog = PreviewStyleDialog(self, self.preview_style)
            self.preview_style_dialog.styleChanged.connect(self.apply_preview_style)
            self.preview_style_dialog.resetRequested.connect(self.reset_preview_style)
        self.preview_style_dialog.set_style(self.preview_style)
        show_foreground(self.preview_style_dialog)

    def apply_preview_style(self, style: PreviewStyleConfig, announce: bool = True) -> None:
        self.preview_style = style
        self.apply_json_preview_style()
        self._save_view_settings()
        self.timing_preview.update()
        self.section_preview.update()
        if self.file_preview_popup.isVisible():
            self.file_preview_popup.apply_preview(self.file_preview_popup.plot.result, self.preview_style)
        if announce:
            self.statusBar().showMessage("Preview-/Diagramm-Stil aktualisiert", 1800)

    def reset_preview_style(self) -> None:
        self.preview_style = PreviewStyleConfig.defaults()
        if hasattr(self, "preview_style_dialog") and self.preview_style_dialog is not None:
            self.preview_style_dialog.set_style(self.preview_style)
        self.apply_preview_style(self.preview_style, announce=False)
        self.statusBar().showMessage("Preview-/Diagramm-Stile zurückgesetzt", 2200)

    def validate_config(self) -> None:
        self.ensure_defaults()



# ===== thermo0d YAML editor integration =====

def _editor_cycle_span(cycle_type: str) -> float:
    return 360.0 if str(cycle_type).upper() == '2T' else 720.0


def _editor_ref_to_absolute(angle_deg: float, reference: str, cycle_type: str) -> float:
    angle = float(angle_deg)
    if str(reference) == 'gas_exchange_tdc' and str(cycle_type).upper() == '4T':
        angle += 360.0
    span = _editor_cycle_span(cycle_type)
    while angle < 0.0:
        angle += span
    while angle >= span:
        angle -= span
    return angle


def _editor_absolute_to_reference(angle_deg: float, cycle_type: str) -> tuple[float, str]:
    span = _editor_cycle_span(cycle_type)
    angle = float(angle_deg)
    while angle < 0.0:
        angle += span
    while angle >= span:
        angle -= span
    if str(cycle_type).upper() == '4T' and angle >= 360.0:
        return angle - 360.0, 'gas_exchange_tdc'
    return angle, 'absolute'


def _editor_load_csv_table(path: Path, expected_cols: int, table_kind: str = "generic") -> list[tuple[float, ...]]:
    if not path.exists():
        return []
    try:
        data = load_numeric_table(path, expected_cols=expected_cols, table_kind=table_kind).data
    except Exception:
        return []
    return [tuple(float(v) for v in row) for row in data.tolist()]


def _editor_load_csv_pairs(path: Path, table_kind: str = "generic") -> list[tuple[float, float]]:
    return [(float(row[0]), float(row[1])) for row in _editor_load_csv_table(path, 2, table_kind=table_kind)]


def _editor_profile_metrics(path: Path, profile_angle_domain: str, cycle_type: str) -> tuple[float, float]:
    pairs = _editor_load_csv_pairs(path, table_kind="valve_lift")
    if not pairs:
        return 1.0, 0.0
    xs = [p[0] for p in pairs]
    ys = [max(0.0, p[1]) for p in pairs]
    active = [i for i, y in enumerate(ys) if y > 1.0e-12]
    if not active:
        base_duration = max(xs[-1] - xs[0], 1.0)
    else:
        base_duration = max(xs[active[-1]] - xs[active[0]], 1.0e-9)
    if str(profile_angle_domain) == 'cam':
        base_duration *= 2.0
    max_lift = max(ys) if ys else 0.0
    span = _editor_cycle_span(cycle_type)
    while base_duration > span and span > 0.0:
        base_duration -= span
    return base_duration, max_lift


def _editor_guess_connection_side(conn: dict[str, Any], cylinder_name: str) -> str:
    from_vol = str(conn.get('from_volume', ''))
    to_vol = str(conn.get('to_volume', ''))
    name = str(conn.get('name', '')).lower()
    if 'intake' in name or 'transfer' in name or 'scavenge' in name:
        return 'intake'
    if 'exhaust' in name:
        return 'exhaust'
    if to_vol == cylinder_name and from_vol != cylinder_name:
        return 'intake'
    return 'exhaust'


def _editor_slot_open_distance(conn: dict[str, Any], engine_block: dict[str, Any], cycle_type: str) -> float:
    if conn.get('opening_mode') == 'by_distance':
        return float(conn.get('distance_from_tdc_m') or 0.0)
    bore = float(engine_block.get('bore_m') or 0.0)
    stroke = float(engine_block.get('stroke_m') or 0.0)
    conrod = float(engine_block.get('conrod_m') or 0.0)
    compression_ratio = float(engine_block.get('compression_ratio') or 10.0)
    open_angle = float(conn.get('opening_angle_deg') or 0.0)
    ref = str(conn.get('opening_reference') or 'absolute')
    theta_abs = _editor_ref_to_absolute(open_angle, ref, cycle_type)
    return max(piston_distance_from_ut(stroke, conrod, theta_abs), 0.0)


def _editor_relative_path(base_dir: Path, path_text: str) -> str:
    if not path_text:
        return ''
    path = Path(path_text)
    if not path.is_absolute():
        return path.as_posix()
    try:
        return path.relative_to(base_dir).as_posix()
    except Exception:
        return path.as_posix()


def _editor_default_wall_heat_dict() -> dict[str, Any]:
    return {
        'model': 'none',
        'variant': 'legacy',
        'c1': 2.28,
        'c2': 0.00324,
        'c3': 0.0,
        'wall_temperature_K': 450.0,
        'wall_area_m2': 0.02,
        'multiplier': 1.0,
        'cucm': 0.0,
        'swirl_number': 0.0,
        'imep_bar': 0.0,
        'dp_mode': 'off',
        'reference_state_mode': 'none',
        'phase_mode': 'legacy',
    }


def _editor_sanitize_wall_heat_config(value: Any) -> dict[str, Any]:
    defaults = _editor_default_wall_heat_dict()
    if not isinstance(value, dict):
        return {'model': 'none'}
    model = str(value.get('model', 'none') or 'none').strip().lower()
    if model != 'woschni':
        return {'model': 'none'}
    variant = str(value.get('variant', defaults['variant']) or defaults['variant']).strip().lower()
    if variant not in WOSCHNI_VARIANT_CHOICES:
        variant = defaults['variant']
    dp_mode = str(value.get('dp_mode', defaults['dp_mode']) or defaults['dp_mode']).strip().lower()
    if dp_mode not in WOSCHNI_DP_MODE_CHOICES:
        dp_mode = defaults['dp_mode']
    ref_mode = str(value.get('reference_state_mode', defaults['reference_state_mode']) or defaults['reference_state_mode']).strip().lower()
    if ref_mode not in WOSCHNI_REF_MODE_CHOICES:
        ref_mode = defaults['reference_state_mode']
    phase_mode = str(value.get('phase_mode', defaults['phase_mode']) or defaults['phase_mode']).strip().lower()
    if phase_mode not in WOSCHNI_PHASE_MODE_CHOICES:
        phase_mode = defaults['phase_mode']
    out = {
        'model': 'woschni',
        'variant': variant,
        'wall_temperature_K': max(float(value.get('wall_temperature_K', defaults['wall_temperature_K']) or defaults['wall_temperature_K']), 1.0),
        'wall_area_m2': max(float(value.get('wall_area_m2', defaults['wall_area_m2']) or defaults['wall_area_m2']), 0.0),
        'multiplier': max(float(value.get('multiplier', defaults['multiplier']) or defaults['multiplier']), 0.0),
        'cucm': float(value.get('cucm', defaults['cucm']) or defaults['cucm']),
        'swirl_number': float(value.get('swirl_number', defaults['swirl_number']) or defaults['swirl_number']),
        'imep_bar': float(value.get('imep_bar', defaults['imep_bar']) or defaults['imep_bar']),
        'dp_mode': dp_mode,
        'reference_state_mode': ref_mode,
        'phase_mode': phase_mode,
    }
    if variant == 'legacy':
        out['c1'] = float(value.get('c1', defaults['c1']) or defaults['c1'])
        out['c2'] = float(value.get('c2', defaults['c2']) or defaults['c2'])
        out['c3'] = float(value.get('c3', defaults['c3']) or defaults['c3'])
    return out


def _editor_engine_default_config(self) -> dict[str, Any]:
    base = {
        'versioning': current_versioning_dict(),
        'engine': {
            'cycle_type': '4T',
            'speed_rpm': 2500.0,
            'bore_m': 0.086,
            'stroke_m': 0.086,
            'conrod_m': 0.143,
            'compression_ratio': 10.5,
            'wall_heat': _editor_default_wall_heat_dict(),
        },
        'gasexchange': {
            'mode': 'valves',
            'valves': {
                'lift_file': '',
                'alphak_file': '',
                'lift_angle_basis': 'cam',
                'cam_to_crank_ratio': 2.0,
                'effective_lift_threshold_mm': 0.0,
                'count_in': 1,
                'count_ex': 1,
                'intake': {
                    'lift_file': '',
                    'alphak_file': '',
                                        'open_deg': 350.0,
                    'max_lift_m': 0.010,
                    '_connection_name': 'intake_valve',
                    '_from_volume': 'intake_plenum',
                    '_to_volume': 'cylinder',
                    '_lift_file': '',
                    '_alpha_k_file': '',
                    '_profile_angle_domain': 'crank',
                    '_opening_reference': 'absolute',
                    '_base_profile_span_deg': 1.0,
                    '_base_profile_max_lift_m': 0.010,
                    '_lash_m': 0.0,
                },
                'exhaust': {
                    'lift_file': '',
                    'alphak_file': '',
                                        'open_deg': 135.0,
                    'max_lift_m': 0.009,
                    '_connection_name': 'exhaust_valve',
                    '_from_volume': 'cylinder',
                    '_to_volume': 'exhaust_plenum',
                    '_lift_file': '',
                    '_alpha_k_file': '',
                    '_profile_angle_domain': 'crank',
                    '_opening_reference': 'absolute',
                    '_base_profile_span_deg': 1.0,
                    '_base_profile_max_lift_m': 0.009,
                    '_lash_m': 0.0,
                },
                'scaling': {
                    'intake': {'angle_scale': 1.0, 'lift_scale': 1.0},
                    'exhaust': {'angle_scale': 1.0, 'lift_scale': 1.0},
                },
            },
            'slots': {
                'forward_discharge_coefficient': 1.0,
                'reverse_discharge_coefficient': 1.0,
                'intake': {
                    'width_m': 0.010,
                    'height_m': 0.012,
                    'count': 1,
                    'offset_from_ut_m': 0.010,
                    'forward_discharge_coefficient': 1.0,
                    'reverse_discharge_coefficient': 1.0,
                    'roof': {'type': 'none', 'len_m': 0.0, 'gamma': 1.0, 'angle_deg': 0.0},
                    '_connection_name': 'transfer_slot',
                    '_from_volume': 'scavenge_plenum',
                    '_to_volume': 'cylinder',
                    '_opening_mode': 'by_distance',
                    '_opening_angle_deg': None,
                    '_discharge_table_file': '',
                },
                'exhaust': {
                    'width_m': 0.012,
                    'height_m': 0.014,
                    'count': 1,
                    'offset_from_ut_m': 0.012,
                    'forward_discharge_coefficient': 1.0,
                    'reverse_discharge_coefficient': 1.0,
                    'roof': {'type': 'none', 'len_m': 0.0, 'gamma': 1.0, 'angle_deg': 0.0},
                    '_connection_name': 'exhaust_slot',
                    '_from_volume': 'cylinder',
                    '_to_volume': 'exhaust_plenum',
                    '_opening_mode': 'by_distance',
                    '_opening_angle_deg': None,
                    '_discharge_table_file': '',
                },
            },
            'ports': {
                'area_file': '',
                'alphak_file': '',
                'intake': {
                    'width_m': 0.018,
                    'height_m': 0.022,
                    'count': 1,
                    'offset_from_ut_m': 0.012,
                    'alphak_file': '',
                    'roof': {'type': 'none', 'len_m': 0.0, 'gamma': 1.0, 'angle_deg': 0.0},
                },
                'exhaust': {
                    'width_m': 0.020,
                    'height_m': 0.024,
                    'count': 1,
                    'offset_from_ut_m': 0.010,
                    'alphak_file': '',
                    'roof': {'type': 'none', 'len_m': 0.0, 'gamma': 1.0, 'angle_deg': 0.0},
                },
            },
        },
    }
    return base


def _editor_import_from_thermo0d(self, loaded: dict[str, Any], path: Path) -> dict[str, Any]:
    base = merge_dicts(_editor_engine_default_config(self), {})
    pre = dict(loaded.get('preprocessing') or {})
    engine_cfg = dict(pre.get('engine') or {})
    base['engine']['cycle_type'] = str(engine_cfg.get('cycle_type') or '4t').upper()
    base['engine']['speed_rpm'] = float(engine_cfg.get('speed_rpm') or base['engine']['speed_rpm'])

    cylinder = None
    for vol in list(pre.get('volumes') or []):
        if isinstance(vol, dict) and str(vol.get('type')) == 'cylinder':
            cylinder = vol
            break
    if cylinder is not None:
        kin = dict(cylinder.get('kinematics') or {})
        for key in ('bore_m', 'stroke_m', 'conrod_m', 'compression_ratio'):
            if key in kin:
                base['engine'][key] = float(kin.get(key) or base['engine'][key])
        base['engine']['wall_heat'] = _editor_sanitize_wall_heat_config(cylinder.get('wall_heat') or {})
        base['engine']['_cylinder_name'] = str(cylinder.get('name') or 'cylinder')
    else:
        base['engine']['_cylinder_name'] = 'cylinder'
    cylinder_name = str(base['engine'].get('_cylinder_name') or 'cylinder')

    connections = list(pre.get('connections') or [])
    has_valve = any(isinstance(conn, dict) and str(conn.get('type')) == 'valve' for conn in connections)
    has_slot = any(isinstance(conn, dict) and str(conn.get('type')) == 'slot' for conn in connections)
    base['gasexchange']['mode'] = 'valves' if has_valve else ('slots' if has_slot else 'valves')

    for conn in connections:
        if not isinstance(conn, dict):
            continue
        ctype = str(conn.get('type') or '')
        if ctype == 'valve':
            side = _editor_guess_connection_side(conn, cylinder_name)
            side_cfg = base['gasexchange']['valves'][side]
            conn_name = str(conn.get('name') or side_cfg.get('_connection_name'))
            from_volume = str(conn.get('from_volume') or side_cfg.get('_from_volume'))
            to_volume = str(conn.get('to_volume') or side_cfg.get('_to_volume'))
            lift_file = str((path.parent / str(conn.get('lift_file') or '')).resolve()) if conn.get('lift_file') else ''
            alpha_file = str((path.parent / str(conn.get('alpha_k_file') or '')).resolve()) if conn.get('alpha_k_file') else ''
            base_duration, base_max_lift = _editor_profile_metrics(Path(lift_file), str(conn.get('profile_angle_domain') or 'crank'), base['engine']['cycle_type'])
            open_abs = _editor_ref_to_absolute(float(conn.get('opening_angle_deg') or 0.0), str(conn.get('opening_reference') or 'absolute'), base['engine']['cycle_type'])
            max_lift = max(base_max_lift * float(conn.get('lift_scale') or 1.0), 0.0)
            side_cfg.update({
                'profile_angle_domain': str(conn.get('profile_angle_domain') or 'crank'),
                'open_deg': open_abs,
                'max_lift_m': max_lift,
                '_connection_name': conn_name,
                '_from_volume': from_volume,
                '_to_volume': to_volume,
                'lift_file': lift_file,
                'alphak_file': alpha_file,
                '_lift_file': lift_file,
                '_alpha_k_file': alpha_file,
                '_profile_angle_domain': str(conn.get('profile_angle_domain') or 'crank'),
                '_opening_reference': str(conn.get('opening_reference') or 'absolute'),
                '_base_profile_span_deg': base_duration,
                '_base_profile_max_lift_m': base_max_lift,
                '_lash_m': float(conn.get('lash_m') or 0.0),
            })
            scaling = base['gasexchange']['valves']['scaling'][side]
            scaling['angle_scale'] = 1.0
            scaling['lift_scale'] = float(conn.get('lift_scale') or 1.0)
            # shared fields as convenience fallbacks
            if not base['gasexchange']['valves'].get('lift_file'):
                base['gasexchange']['valves']['lift_file'] = lift_file
            if not base['gasexchange']['valves'].get('alphak_file'):
                base['gasexchange']['valves']['alphak_file'] = alpha_file
        elif ctype == 'slot':
            side = _editor_guess_connection_side(conn, cylinder_name)
            side_cfg = base['gasexchange']['slots'][side]
            side_cfg.update({
                'width_m': float(conn.get('width_m') or side_cfg['width_m']),
                'height_m': float(conn.get('height_m') or side_cfg['height_m']),
                'count': int(conn.get('number_of_identical_holes') or side_cfg['count']),
                'offset_from_ut_m': _editor_slot_open_distance(conn, base['engine'], base['engine']['cycle_type']),
                'forward_discharge_coefficient': float((conn.get('discharge_coefficients') or {}).get('forward_cd') or side_cfg['forward_discharge_coefficient']),
                'reverse_discharge_coefficient': float((conn.get('discharge_coefficients') or {}).get('reverse_cd') or side_cfg['reverse_discharge_coefficient']),
                '_connection_name': str(conn.get('name') or side_cfg.get('_connection_name')),
                '_from_volume': str(conn.get('from_volume') or side_cfg.get('_from_volume')),
                '_to_volume': str(conn.get('to_volume') or side_cfg.get('_to_volume')),
                '_opening_mode': str(conn.get('opening_mode') or 'by_distance'),
                '_opening_angle_deg': conn.get('opening_angle_deg'),
                '_discharge_table_file': str((path.parent / str((conn.get('discharge_coefficients') or {}).get('table_file') or '')).resolve()) if (conn.get('discharge_coefficients') or {}).get('table_file') else '',
            })
            side_cfg['roof'] = {
                'type': 'none',
                'len_m': 0.0,
                'gamma': 1.0,
                'angle_deg': 0.0,
            }
            coeffs = dict(conn.get('discharge_coefficients') or {})
            if coeffs.get('mode') == 'constant':
                side_cfg['forward_discharge_coefficient'] = float(coeffs.get('forward_cd') or side_cfg['forward_discharge_coefficient'])
                side_cfg['reverse_discharge_coefficient'] = float(coeffs.get('reverse_cd') or side_cfg['reverse_discharge_coefficient'])
    return base


def _editor_import_from_free_piston_preview(self, loaded: dict[str, Any], path: Path) -> dict[str, Any]:
    base = merge_dicts(_editor_engine_default_config(self), {})
    pre = dict(loaded.get('preprocessing') or {})
    engine_cfg = dict(pre.get('engine') or {})
    base['engine']['cycle_type'] = str(engine_cfg.get('cycle_type') or '2t').upper()
    base['engine']['speed_rpm'] = float(engine_cfg.get('speed_rpm') or base['engine']['speed_rpm'])
    base['engine']['_architecture'] = 'free_piston'

    cylinder = None
    for vol in list(pre.get('volumes') or []):
        if isinstance(vol, dict) and str(vol.get('type')) == 'cylinder':
            cylinder = vol
            break
    if cylinder is not None:
        kin = dict(cylinder.get('kinematics') or {})
        for key in ('bore_m', 'stroke_m', 'conrod_m', 'compression_ratio'):
            if key in kin:
                base['engine'][key] = float(kin.get(key) or base['engine'][key])
        base['engine']['wall_heat'] = _editor_sanitize_wall_heat_config(cylinder.get('wall_heat') or {})
        base['engine']['_cylinder_name'] = str(cylinder.get('name') or 'cylinder')
    else:
        base['engine']['_cylinder_name'] = 'cylinder'

    preview_cfg = loaded.get('gasexchange')
    if isinstance(preview_cfg, dict):
        base['gasexchange'] = merge_dicts(base['gasexchange'], copy.deepcopy(preview_cfg))
    return base


def _editor_build_free_piston_document(self) -> dict[str, Any]:
    base_doc = copy.deepcopy(getattr(self, '_loaded_document', {}) or {})
    if not isinstance(base_doc, dict):
        base_doc = {}
    base_doc.setdefault('versioning', current_versioning_dict())
    base_doc.setdefault('modeling', {'architecture': 'free_piston'})
    base_doc.setdefault('preprocessing', {})
    base_doc.setdefault('simulation', {
        'dt_s': 2.0e-5,
        'total_cycles': 3,
        'save_last_cycles': 1,
        'solver': {'kind': 'rk4', 'rtol': 1.0e-6, 'atol': 1.0e-9},
    })
    base_doc.setdefault('postprocessing', {
        'csv_path': 'results/output.csv',
        'csv_separator': ';',
        'sampling': {'mode': 'time', 'step_s': 1.0e-4},
    })
    pre = dict(base_doc.get('preprocessing') or {})
    base_doc['preprocessing'] = pre
    pre.setdefault('gas_properties', {'cp_J_per_kgK': 1005.0, 'cv_J_per_kgK': 718.0, 'R_J_per_kgK': 287.0})
    pre.setdefault('features', {'mass_flow': False, 'wall_heat': False, 'combustion': False, 'evaporation': False, 'pv_work': True})
    cycle_type = '2t' if self.cycle_type() == '2T' else '4t'
    speed_rpm = float(deep_get(self.config_data, 'engine.speed_rpm', 25.0) or 25.0)
    pre['engine'] = {'cycle_type': cycle_type, 'speed_rpm': speed_rpm}

    volumes = [copy.deepcopy(vol) for vol in list(pre.get('volumes') or []) if isinstance(vol, dict)]
    cylinder_name = str(deep_get(self.config_data, 'engine._cylinder_name', 'cylinder') or 'cylinder')
    cyl_idx = next((i for i, vol in enumerate(volumes) if str(vol.get('type')) == 'cylinder'), None)
    if cyl_idx is None:
        cylinder_block = {
            'name': cylinder_name,
            'type': 'cylinder',
            'initial_pressure_Pa': 101325.0,
            'initial_temperature_K': 300.0,
            'kinematics': {'type': 'crank_slider', 'bore_m': 0.086, 'stroke_m': 0.086, 'conrod_m': 0.143, 'compression_ratio': 10.5, 'phase_deg': 0.0},
            'wall_heat': _editor_sanitize_wall_heat_config(deep_get(self.config_data, 'engine.wall_heat', {}) or {}),
            'combustion': {'model': 'none'},
            'evaporation': {'model': 'none'},
        }
        volumes.insert(0, cylinder_block)
    else:
        cylinder_block = dict(volumes[cyl_idx])
        volumes[cyl_idx] = cylinder_block
    cylinder_block['name'] = cylinder_name
    cylinder_block['type'] = 'cylinder'
    kin = dict(cylinder_block.get('kinematics') or {})
    kin.update({
        'type': 'crank_slider',
        'bore_m': float(deep_get(self.config_data, 'engine.bore_m', 0.086) or 0.086),
        'stroke_m': float(deep_get(self.config_data, 'engine.stroke_m', 0.086) or 0.086),
        'conrod_m': float(deep_get(self.config_data, 'engine.conrod_m', 0.143) or 0.143),
        'compression_ratio': float(deep_get(self.config_data, 'engine.compression_ratio', 10.5) or 10.5),
        'phase_deg': float(kin.get('phase_deg', 0.0) or 0.0),
    })
    cylinder_block['kinematics'] = kin
    cylinder_block['wall_heat'] = _editor_sanitize_wall_heat_config(deep_get(self.config_data, 'engine.wall_heat', {}) or {})
    pre['volumes'] = volumes[:1]
    pre['connections'] = []
    base_doc['gasexchange'] = copy.deepcopy(self.config_data.get('gasexchange', {}))
    return stamp_current_versioning(base_doc)


def _editor_editor_load(self, path: Path) -> None:
    path = Path(path)
    try:
        if path.suffix.lower() in {'.yaml', '.yml'}:
            loaded = yaml.safe_load(path.read_text(encoding='utf-8')) or {}
        else:
            loaded = json.loads(path.read_text(encoding='utf-8'))
    except Exception as exc:
        show_critical(self, 'Laden fehlgeschlagen', str(exc))
        return

    if isinstance(loaded, dict) and requires_version_upgrade(loaded):
        loaded_schema = config_schema_version_from_document(loaded)
        answer = ask_question(
            self,
            'Alte Konfigurationsversion',
            build_upgrade_message(path, loaded_schema),
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button=QMessageBox.StandardButton.Yes,
        )
        if answer == QMessageBox.StandardButton.Yes:
            try:
                loaded = migrate_config_file_in_place(path, loaded)
                self.statusBar().showMessage(
                    f'Konfigurationsversion aktualisiert: Schema {loaded_schema} → {CURRENT_CONFIG_SCHEMA_VERSION}',
                    5000,
                )
            except Exception as exc:
                show_critical(self, 'Versionsupdate fehlgeschlagen', str(exc))
                return

    if isinstance(loaded, dict) and 'preprocessing' in loaded:
        self._loaded_document = copy.deepcopy(loaded)
        self._loaded_document_format = 'thermo0d_yaml'
        architecture = str(deep_get(loaded, 'modeling.architecture', 'classic') or 'classic').strip().lower()
        if architecture == 'free_piston':
            self.config_data = _editor_import_from_free_piston_preview(self, loaded, path)
        else:
            self.config_data = _editor_import_from_thermo0d(self, loaded, path)
    else:
        subset = {
            'engine': copy.deepcopy((loaded or {}).get('engine', {})),
            'gasexchange': copy.deepcopy((loaded or {}).get('gasexchange', {})),
        }
        self._loaded_document = copy.deepcopy(loaded) if isinstance(loaded, dict) else {}
        self._loaded_document_format = 'subset_config'
        self.config_data = merge_dicts(self.default_config(), subset)
    self.current_path = path.resolve()
    self.settings.setValue('files/last_config_path', str(self.current_path))
    self.settings.sync()
    self.ensure_defaults()
    self.refresh_ui_from_model()
    self.statusBar().showMessage(f'Geladen: {path}', 3500)


def _editor_extract_engine_internal(self) -> dict[str, Any]:
    engine_internal = copy.deepcopy(self.config_data.get('engine', {}))
    engine_out: dict[str, Any] = {}
    for key, value in engine_internal.items():
        if str(key).startswith('_') or key == 'speed_rpm':
            continue
        if key in {'bore_m', 'stroke_m', 'conrod_m'}:
            out_key = self.engine_save_aliases.get(key, key)
            engine_out[out_key] = value
        else:
            engine_out[key] = value
    return engine_out


def _compat_volume_initial_volume_m3(vol: dict[str, Any]) -> float:
    if str(vol.get('type') or '') == 'plenum':
        return float(vol.get('fixed_volume_m3') or 0.0)
    kin = dict(vol.get('kinematics') or {})
    bore = float(kin.get('bore_m') or 0.0)
    stroke = float(kin.get('stroke_m') or 0.0)
    conrod = float(kin.get('conrod_m') or 0.0)
    compression_ratio = float(kin.get('compression_ratio') or 0.0)
    phase_deg = float(kin.get('phase_deg') or 0.0)
    if bore <= 0.0 or stroke <= 0.0 or conrod <= 0.0 or compression_ratio <= 1.0:
        return 0.0
    theta = math.radians(phase_deg % 360.0)
    area = 0.25 * math.pi * bore * bore
    r = 0.5 * stroke
    sin_t = math.sin(theta)
    cos_t = math.cos(theta)
    under = max(conrod * conrod - (r * sin_t) * (r * sin_t), 1.0e-18)
    x = r * (1.0 - cos_t) + conrod - math.sqrt(under)
    vs = area * stroke
    vc = vs / (compression_ratio - 1.0)
    return vc + area * x


def _compat_normalize_initial_states(base_doc: dict[str, Any]) -> None:
    sync_initial_states_inplace(base_doc)


def _editor_build_thermo0d_document(self) -> dict[str, Any]:
    base_doc = copy.deepcopy(getattr(self, '_loaded_document', {}) or {})
    if not isinstance(base_doc, dict) or 'preprocessing' not in base_doc:
        base_doc = {
            'versioning': current_versioning_dict(),
            'preprocessing': {},
            'simulation': {
                'dt_s': 2.0e-5,
                'total_cycles': 3,
                'save_last_cycles': 2,
                'solver': {'kind': 'rk4', 'rtol': 1.0e-6, 'atol': 1.0e-9},
            },
            'postprocessing': {
                'csv_path': 'results/output.csv',
                'csv_separator': ';',
                'sampling': {'mode': 'time', 'step_s': 1.0e-4},
            },
        }
    pre = dict(base_doc.get('preprocessing') or {})
    base_doc['preprocessing'] = pre
    pre.setdefault('gas_properties', {'cp_J_per_kgK': 1005.0, 'cv_J_per_kgK': 718.0, 'R_J_per_kgK': 287.0})
    pre.setdefault('features', {'mass_flow': True, 'wall_heat': True, 'combustion': True, 'evaporation': True, 'pv_work': True})

    cycle_type = '2t' if self.cycle_type() == '2T' else '4t'
    speed_rpm = float(deep_get(self.config_data, 'engine.speed_rpm', 2500.0) or 2500.0)
    pre['engine'] = {'cycle_type': cycle_type, 'speed_rpm': speed_rpm}

    volumes = list(pre.get('volumes') or [])
    cylinder_name = str(deep_get(self.config_data, 'engine._cylinder_name', 'cylinder') or 'cylinder')
    cyl_idx = next((i for i, vol in enumerate(volumes) if isinstance(vol, dict) and str(vol.get('type')) == 'cylinder'), None)
    cylinder_block = None
    if cyl_idx is None:
        cylinder_block = {
            'name': cylinder_name,
            'type': 'cylinder',
            'initial_pressure_Pa': 1.0e6,
            'initial_temperature_K': 360.0,
            'kinematics': {'type': 'crank_slider', 'bore_m': 0.086, 'stroke_m': 0.086, 'conrod_m': 0.143, 'compression_ratio': 10.5, 'phase_deg': 0.0},
            'wall_heat': _editor_sanitize_wall_heat_config(deep_get(self.config_data, 'engine.wall_heat', {}) or {}),
            'combustion': {'model': 'none'},
            'evaporation': {'model': 'none'},
        }
        volumes.insert(0, cylinder_block)
    else:
        cylinder_block = dict(volumes[cyl_idx])
        volumes[cyl_idx] = cylinder_block
    cylinder_block['name'] = cylinder_name
    cylinder_block['type'] = 'cylinder'
    kin = dict(cylinder_block.get('kinematics') or {})
    kin.update({
        'type': 'crank_slider',
        'bore_m': float(deep_get(self.config_data, 'engine.bore_m', 0.086) or 0.086),
        'stroke_m': float(deep_get(self.config_data, 'engine.stroke_m', 0.086) or 0.086),
        'conrod_m': float(deep_get(self.config_data, 'engine.conrod_m', 0.143) or 0.143),
        'compression_ratio': float(deep_get(self.config_data, 'engine.compression_ratio', 10.5) or 10.5),
        'phase_deg': float(kin.get('phase_deg', 0.0) or 0.0),
    })
    cylinder_block['kinematics'] = kin
    cylinder_block['wall_heat'] = _editor_sanitize_wall_heat_config(deep_get(self.config_data, 'engine.wall_heat', {}) or {})
    pre['volumes'] = volumes

    connections: list[dict[str, Any]] = []
    mode = self.active_gasexchange_mode()
    cfg_dir = self.current_path.parent if self.current_path else Path.cwd()

    if mode == 'valves':
        for side in ('intake', 'exhaust'):
            side_cfg = dict(deep_get(self.config_data, f'gasexchange.valves.{side}', {}) or {})
            conn_name = str(side_cfg.get('_connection_name') or f'{side}_valve')
            from_volume = str(side_cfg.get('_from_volume') or ('cylinder' if side == 'exhaust' else 'intake_plenum'))
            to_volume = str(side_cfg.get('_to_volume') or ('exhaust_plenum' if side == 'exhaust' else 'cylinder'))
            open_deg = float(side_cfg.get('open_deg') or 0.0)
            max_lift = max(float(side_cfg.get('max_lift_m') or 0.0), 0.0)
            base_max_lift = max(float(side_cfg.get('_base_profile_max_lift_m') or max_lift or 1.0e-9), 1.0e-9)
            lift_file = str(side_cfg.get('lift_file') or side_cfg.get('_lift_file') or '')
            alpha_file = str(side_cfg.get('alphak_file') or side_cfg.get('_alpha_k_file') or '')
            rel_lift_file = _editor_relative_path(cfg_dir, lift_file)
            rel_alpha_file = _editor_relative_path(cfg_dir, alpha_file)
            opening_angle_deg, opening_reference = _editor_absolute_to_reference(open_deg, self.cycle_type())
            connections.append({
                'name': conn_name,
                'type': 'valve',
                'from_volume': from_volume,
                'to_volume': to_volume,
                'opening_angle_deg': opening_angle_deg,
                'opening_reference': opening_reference,
                'profile_angle_domain': str(side_cfg.get('profile_angle_domain') or side_cfg.get('_profile_angle_domain') or 'crank'),
                'lift_scale': max_lift / base_max_lift if base_max_lift > 1.0e-12 else 1.0,
                'lash_m': float(side_cfg.get('_lash_m') or 0.0),
                'lift_file': rel_lift_file,
                'alpha_k_file': rel_alpha_file,
            })
    else:
        for side in ('intake', 'exhaust'):
            side_cfg = dict(deep_get(self.config_data, f'gasexchange.slots.{side}', {}) or {})
            conn_name = str(side_cfg.get('_connection_name') or (f'{side}_slot'))
            from_volume = str(side_cfg.get('_from_volume') or ('cylinder' if side == 'exhaust' else 'scavenge_plenum'))
            to_volume = str(side_cfg.get('_to_volume') or ('exhaust_plenum' if side == 'exhaust' else 'cylinder'))
            table_file = str(side_cfg.get('_discharge_table_file') or '')
            coeff_mode = 'table' if table_file else 'constant'
            coeffs: dict[str, Any]
            if coeff_mode == 'table':
                coeffs = {
                    'mode': 'table',
                    'table_file': _editor_relative_path(cfg_dir, table_file),
                }
            else:
                coeffs = {
                    'mode': 'constant',
                    'forward_cd': float(side_cfg.get('forward_discharge_coefficient') or deep_get(self.config_data, 'gasexchange.slots.forward_discharge_coefficient', 1.0) or 1.0),
                    'reverse_cd': float(side_cfg.get('reverse_discharge_coefficient') or deep_get(self.config_data, 'gasexchange.slots.reverse_discharge_coefficient', 1.0) or 1.0),
                }
            connections.append({
                'name': conn_name,
                'type': 'slot',
                'from_volume': from_volume,
                'to_volume': to_volume,
                'source_of_data': 'rectangle',
                'opening_mode': 'by_distance',
                'distance_from_tdc_m': float(side_cfg.get('offset_from_ut_m') or 0.0),
                'opening_angle_deg': None,
                'piston_height_if_crankcase_m': 0.0,
                'entrance_angle_deg': 0.0,
                'width_m': float(side_cfg.get('width_m') or 0.0),
                'height_m': float(side_cfg.get('height_m') or 0.0),
                'open_fillet_radius_m': 0.0,
                'full_fillet_radius_m': 0.0,
                'number_of_identical_holes': int(side_cfg.get('count') or 1),
                'discharge_coefficients': coeffs,
            })
    pre['connections'] = connections
    return stamp_current_versioning(base_doc)


def _editor_editor_save(self) -> None:
    if self.current_path is None:
        self.save_json_as()
        return
    try:
        if self.current_path.suffix.lower() in {'.yaml', '.yml'} or getattr(self, '_loaded_document_format', '') == 'thermo0d_yaml':
            architecture = str(deep_get(getattr(self, '_loaded_document', {}) or {}, 'modeling.architecture', deep_get(self.config_data, 'engine._architecture', 'classic')) or 'classic').strip().lower()
            if architecture == 'free_piston':
                data = stamp_current_versioning(_editor_build_free_piston_document(self))
            else:
                data = stamp_current_versioning(_editor_build_thermo0d_document(self))
            with self.current_path.open('w', encoding='utf-8') as handle:
                yaml.safe_dump(data, handle, sort_keys=False, allow_unicode=True)
        else:
            data = stamp_current_versioning(self.serialize_subset())
            with self.current_path.open('w', encoding='utf-8') as handle:
                json.dump(data, handle, indent=2, ensure_ascii=False)
                handle.write('\n')
    except Exception as exc:
        show_critical(self, 'Speichern fehlgeschlagen', str(exc))
        return
    if self.current_path is not None:
        self.settings.setValue('files/last_config_path', str(self.current_path.resolve()))
        self.settings.sync()
    self.statusBar().showMessage(f'Gespeichert: {self.current_path}', 3000)
    self._update_statusbar_fields()


def _editor_editor_save_as(self) -> None:
    start_dir = str(self.current_path.parent if self.current_path else Path.cwd())
    filename, _ = get_save_file_name(self, 'Konfiguration speichern unter', start_dir, 'YAML-Dateien (*.yaml *.yml);;JSON-Dateien (*.json)')
    if not filename:
        return
    path = Path(filename)
    if path.suffix.lower() not in {'.yaml', '.yml', '.json'}:
        path = path.with_suffix('.yaml')
    self.current_path = path
    self.save_json()
    self.statusBar().showMessage(f'Gespeichert unter: {self.current_path}', 3000)


def _editor_editor_load_via_dialog(self) -> None:
    start_dir = str(self.current_path.parent if self.current_path else Path.cwd())
    filename, _ = get_open_file_name(self, 'Konfiguration laden', start_dir, 'YAML-/JSON-Dateien (*.yaml *.yml *.json);;Alle Dateien (*.*)')
    if filename:
        self.load_json(Path(filename))


def _editor_editor_serialize_subset(self) -> dict[str, Any]:
    return {'engine': _editor_extract_engine_internal(self), 'gasexchange': copy.deepcopy(self.config_data.get('gasexchange', {}))}


EngineGasExchangeEditor.default_config = _editor_engine_default_config
EngineGasExchangeEditor.load_json = _editor_editor_load
EngineGasExchangeEditor.save_json = _editor_editor_save
EngineGasExchangeEditor.save_json_as = _editor_editor_save_as
EngineGasExchangeEditor.load_json_via_dialog = _editor_editor_load_via_dialog
EngineGasExchangeEditor.serialize_subset = _editor_editor_serialize_subset


def launch(config_path: str | Path | None = None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)
    window = EngineGasExchangeEditor(config_path)
    show_foreground(window)
    return app.exec()


def main() -> int:
    parser = argparse.ArgumentParser(description="EngineGasExchangeEditor")
    parser.add_argument("config", nargs="?", help="Pfad zu einer config.yaml / config.yml")
    args = parser.parse_args()
    return launch(args.config)


if __name__ == "__main__":
    raise SystemExit(main())
