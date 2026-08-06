from __future__ import annotations

import math
import json
import os
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from PySide6.QtCore import QByteArray, QMimeData, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QDrag, QFont, QPainter, QPainterPath, QPalette, QPen, QCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDockWidget,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsPathItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QStyleFactory,
    QTabWidget,
    QTextEdit,
    QToolBar,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMenu,
)
from PySide6.QtCore import QSettings

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
from thermo0d.config.schema_meta import build_context_summary, get_schema_hint
from thermo0d.config.schema_meta import (
    ANGLE_REFERENCES,
    PROFILE_ANGLE_DOMAINS,
    SAMPLING_MODES,
    PLOT_SOURCES,
    SOLVER_KINDS,
    meta_for,
)

from thermo0d.gui.dialogs import ask_question, get_open_file_name, get_save_file_name, get_text, show_information, show_warning, show_critical, show_foreground
MIME_PALETTE = "application/x-thermo0d-topology-palette"
NODE_SIZE = (170.0, 74.0)
CONNECTION_NODE_SIZE = (58.0, 34.0)
CONNECTION_LABEL_WIDTH = 150.0
CONNECTION_TYPES = {"valve", "slot", "orifice", "check_valve"}
VOLUME_TYPES = {"cylinder", "plenum", "environment", "bounce_chamber"}
TYPE_COLORS = {
    "cylinder": QColor("#2563eb"),
    "plenum": QColor("#0f766e"),
    "environment": QColor("#16a34a"),
    "bounce_chamber": QColor("#0891b2"),
    "valve": QColor("#1d4ed8"),
    "slot": QColor("#b91c1c"),
    "orifice": QColor("#7c3aed"),
    "check_valve": QColor("#c2410c"),
}


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _deepcopy_jsonable(obj: Any) -> Any:
    return json.loads(json.dumps(obj))


def _merge_defaults_inplace(target: dict[str, Any], defaults: dict[str, Any]) -> None:
    for key, value in defaults.items():
        if key not in target:
            target[key] = _deepcopy_jsonable(value)
            continue
        if isinstance(target.get(key), dict) and isinstance(value, dict):
            _merge_defaults_inplace(target[key], value)


def _fill_ref_types_for_editor_inplace(state: dict[str, Any]) -> None:
    preprocessing = state.get("preprocessing")
    if not isinstance(preprocessing, dict):
        return
    submodels = preprocessing.get("submodels")
    if not isinstance(submodels, dict):
        return

    def _merged_ref(item: dict[str, Any], library: dict[str, Any]) -> dict[str, Any]:
        ref_name = str(item.get("ref", "") or "").strip()
        ref_model = library.get(ref_name) if ref_name else None
        if not isinstance(ref_model, dict):
            return item
        merged = _deepcopy_jsonable(ref_model)
        _merge_defaults_inplace(item, merged)
        return item

    def _merge_nested_submodel(item: dict[str, Any], key: str) -> None:
        value = item.get(key)
        library = submodels.get(key)
        if not isinstance(value, dict) or not isinstance(library, dict):
            return
        ref_name = str(value.get("ref", "") or "").strip()
        ref_model = library.get(ref_name) if ref_name else None
        if isinstance(ref_model, dict):
            _merge_defaults_inplace(value, _deepcopy_jsonable(ref_model))

    def _split_legacy_ignition(item: dict[str, Any]) -> None:
        combustion = item.get("combustion")
        if not isinstance(combustion, dict) or combustion.get("model") != "hcci_diesel" or isinstance(combustion.get("ignition"), dict):
            return
        ignition_keys = {
            "ignition_model", "ignition_delay_table_npz", "tau_A_s", "tau_pressure_exponent",
            "tau_activation_temperature_K", "tau_activation_energy_J_per_kg", "tau_reference_pressure_Pa",
            "tau_reference_lambda", "lambda_slowdown_exponent", "residual_slowdown_factor",
            "beck_c1_s", "beck_c2", "beck_reference_pressure_bar", "beck_reference_o2_percent",
            "beck_cf_fuel_name", "cool_flame_enabled", "cool_flame_burn_model",
            "cool_flame_energy_fraction", "cool_flame_duration_ms", "cool_flame_a", "cool_flame_m",
            "start_temperature_min_K", "start_pressure_min_Pa", "max_ignition_delay_s",
            "accumulation_start_mode", "accumulation_start_distance_from_tdc_m",
            "accumulation_start_distance_from_tdc_mm", "accumulation_end_mode",
        }
        ignition: dict[str, Any] = {"model": combustion.get("ignition_model", "livengood_wu")}
        for key in ignition_keys:
            if key == "ignition_model":
                continue
            if key in combustion:
                ignition[key] = combustion.get(key)
        combustion["ignition"] = ignition

    def _fill_group(items_key: str, library_key: str) -> None:
        items = preprocessing.get(items_key)
        library = submodels.get(library_key)
        if not isinstance(items, list) or not isinstance(library, dict):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            _merged_ref(item, library)
            if items_key == "volumes":
                for nested_key in ("wall_heat", "wall_temperature", "combustion", "evaporation"):
                    _merge_nested_submodel(item, nested_key)
                _merge_nested_submodel(item.get("combustion", {}) if isinstance(item.get("combustion"), dict) else {}, "ignition")
                _split_legacy_ignition(item)
            if items_key == "connections":
                _merge_nested_submodel(item, "discharge_coefficients")

    _fill_group("volumes", "volumes")
    _fill_group("connections", "connections")


def _format_yaml_value(value: Any) -> str:
    if value is None or value == "":
        return ""
    try:
        dumped = yaml.safe_dump(value, sort_keys=False, allow_unicode=True)
    except Exception:
        return str(value)
    return dumped.strip()

def _volume_initial_volume_m3(vol: dict[str, Any], cycle_type: str) -> float:
    vol_type = str(vol.get("type") or "")
    if vol_type == "plenum":
        return float(vol.get("fixed_volume_m3") or 0.0)
    if vol_type == "environment":
        return 0.0
    kin = dict(vol.get("kinematics") or {})
    bore = float(kin.get("bore_m") or 0.0)
    stroke = float(kin.get("stroke_m") or 0.0)
    conrod = float(kin.get("conrod_m") or 0.0)
    compression_ratio = float(kin.get("compression_ratio") or 0.0)
    phase_deg = float(kin.get("phase_deg") or 0.0)
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


def _sanitize_disabled_submodels_inplace(state: dict[str, Any]) -> None:
    preprocessing = state.get("preprocessing", {})
    if not isinstance(preprocessing, dict):
        return
    for vol in preprocessing.get("volumes", []):
        if not isinstance(vol, dict):
            continue
        wall_heat = vol.get("wall_heat")
        if isinstance(wall_heat, dict) and wall_heat.get("model") == "none":
            vol["wall_heat"] = {"model": "none"}
        wall_temperature = vol.get("wall_temperature")
        if isinstance(wall_temperature, dict) and wall_temperature.get("model") == "none":
            vol["wall_temperature"] = {"model": "none"}
        combustion = vol.get("combustion")
        if isinstance(combustion, dict) and combustion.get("model") == "none":
            vol["combustion"] = {"model": "none"}
        evaporation = vol.get("evaporation")
        if isinstance(evaporation, dict) and evaporation.get("model") == "none":
            vol["evaporation"] = {"model": "none"}


def _normalize_initial_states_inplace(state: dict[str, Any]) -> None:
    sync_initial_states_inplace(state)


def _sanitize_mode_dependent_fields_inplace(state: dict[str, Any]) -> None:
    post = state.get("postprocessing")
    if isinstance(post, dict):
        sampling = post.get("sampling")
        if isinstance(sampling, dict):
            if sampling.get("mode") == "time":
                sampling.pop("step_deg", None)
            elif sampling.get("mode") == "crank_angle":
                sampling.pop("step_s", None)

    preprocessing = state.get("preprocessing")
    if not isinstance(preprocessing, dict):
        return

    for vol in preprocessing.get("volumes", []):
        if not isinstance(vol, dict):
            continue
        combustion = vol.get("combustion")
        if not isinstance(combustion, dict) or combustion.get("model") != "vibe":
            if isinstance(combustion, dict) and combustion.get("model") == "hcci_diesel" and isinstance(combustion.get("ignition"), dict):
                for key in (
                    "ignition_model", "ignition_delay_table_npz", "tau_A_s", "tau_pressure_exponent",
                    "tau_activation_temperature_K", "tau_activation_energy_J_per_kg", "tau_reference_pressure_Pa",
                    "tau_reference_lambda", "lambda_slowdown_exponent", "residual_slowdown_factor",
                    "beck_c1_s", "beck_c2", "beck_reference_pressure_bar", "beck_reference_o2_percent",
                    "beck_cf_fuel_name", "cool_flame_enabled", "cool_flame_burn_model",
                    "cool_flame_energy_fraction", "cool_flame_duration_ms", "cool_flame_a", "cool_flame_m",
                    "start_temperature_min_K", "start_pressure_min_Pa", "max_ignition_delay_s",
                    "accumulation_start_mode", "accumulation_start_distance_from_tdc_m",
                    "accumulation_start_distance_from_tdc_mm", "accumulation_end_mode",
                ):
                    combustion.pop(key, None)
            continue
        start_mode = combustion.get("start_mode")
        if start_mode == "angle":
            combustion.pop("start_hub_m", None)
            combustion.pop("hign_m", None)
            combustion.pop("hign_mm", None)
        elif start_mode == "compression_hub":
            combustion.pop("start_deg", None)
            combustion.pop("hign_m", None)
            combustion.pop("hign_mm", None)
        elif start_mode == "hign_position":
            combustion.pop("start_deg", None)
            combustion.pop("start_hub_m", None)
        elif start_mode == "expansion_distance_from_tdc":
            combustion.pop("start_deg", None)
            combustion.pop("start_hub_m", None)

        duration_mode = combustion.get("duration_mode")
        if duration_mode is None:
            if combustion.get("duration_s") is not None or combustion.get("duration_ms") is not None:
                duration_mode = "time"
            elif combustion.get("duration_hub_m") is not None:
                duration_mode = "compression_hub"
            else:
                duration_mode = "angle"
        if duration_mode == "angle":
            combustion.pop("duration_hub_m", None)
            combustion.pop("duration_s", None)
            combustion.pop("duration_ms", None)
        elif duration_mode == "compression_hub":
            combustion.pop("duration_deg", None)
            combustion.pop("duration_s", None)
            combustion.pop("duration_ms", None)
        elif duration_mode == "time":
            combustion.pop("duration_deg", None)
            combustion.pop("duration_hub_m", None)

    for conn in preprocessing.get("connections", []):
        if not isinstance(conn, dict):
            continue
        coeffs = conn.get("discharge_coefficients")
        if not isinstance(coeffs, dict):
            continue
        if coeffs.get("mode") == "constant":
            coeffs.pop("table_file", None)
        elif coeffs.get("mode") == "table":
            coeffs.pop("forward_cd", None)
            coeffs.pop("reverse_cd", None)


def _styled_message(parent: QWidget, title: str, text: str) -> None:
    show_information(parent, title, text)


@dataclass
class EdgeVisual:
    conn_id: str
    role: str  # from/to
    path_item: QGraphicsPathItem
    label_item: QGraphicsTextItem


class DiagramNodeItem(QGraphicsRectItem):
    handle_size = 12.0

    def __init__(self, model_id: str, item_type: str, title: str, subtitle: str, parent: QWidget | None = None):
        default_w, default_h = self.default_size_for_type(item_type)
        super().__init__(0.0, 0.0, default_w, default_h)
        self.model_id = model_id
        self.item_type = item_type
        self.title = title
        self.subtitle = subtitle
        self.editor = parent
        self._resizing = False
        self._resize_origin = QPointF()
        self._start_rect = QRectF()
        self.setFlags(
            QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.title_item = QGraphicsTextItem(self.title, self)
        self.subtitle_item = QGraphicsTextItem(self.subtitle, self)
        title_font = QFont("Segoe UI", 8 if self.item_type in CONNECTION_TYPES else 10)
        title_font.setBold(True)
        self.title_item.setFont(title_font)
        self.title_item.setDefaultTextColor(Qt.GlobalColor.white)
        self.subtitle_item.setFont(QFont("Segoe UI", 7 if self.item_type in CONNECTION_TYPES else 8))
        self.subtitle_item.setDefaultTextColor(QColor("#cbd5e1"))
        self._layout_text()
        self._update_style(False)

    @staticmethod
    def default_size_for_type(item_type: str) -> tuple[float, float]:
        if item_type in CONNECTION_TYPES:
            return CONNECTION_NODE_SIZE
        return NODE_SIZE

    def _layout_text(self) -> None:
        if self.item_type in CONNECTION_TYPES:
            self.title_item.setPos(0.0, self.rect().height() + 3.0)
            self.subtitle_item.setPos(0.0, self.rect().height() + 19.0)
            self.title_item.setTextWidth(CONNECTION_LABEL_WIDTH)
            self.subtitle_item.setTextWidth(CONNECTION_LABEL_WIDTH)
            return
        self.title_item.setPos(12.0, 8.0)
        self.subtitle_item.setPos(12.0, 34.0)
        self.title_item.setTextWidth(max(40.0, self.rect().width() - 24.0))
        self.subtitle_item.setTextWidth(max(40.0, self.rect().width() - 24.0))

    def set_labels(self, title: str, subtitle: str) -> None:
        self.title = title
        self.subtitle = subtitle
        self.title_item.setPlainText(title)
        self.subtitle_item.setPlainText(subtitle)
        self._layout_text()

    def _handle_rect(self) -> QRectF:
        r = self.rect()
        s = self.handle_size
        return QRectF(r.width() - s - 3.0, r.height() - s - 3.0, s, s)

    def _update_style(self, hover: bool) -> None:
        base = TYPE_COLORS.get(self.item_type, QColor("#334155"))
        pen_color = QColor("#e5e7eb") if self.isSelected() else QColor(base).lighter(135 if hover else 115)
        fill = QColor(base)
        fill.setAlpha(215 if hover else 180)
        self.setBrush(fill)
        self.setPen(QPen(pen_color, 2.0 if self.isSelected() else 1.6))

    def hoverEnterEvent(self, event):
        self._update_style(True)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._update_style(False)
        self.unsetCursor()
        super().hoverLeaveEvent(event)

    def hoverMoveEvent(self, event):
        self.setCursor(Qt.SizeFDiagCursor if self._handle_rect().contains(event.pos()) else Qt.ArrowCursor)
        super().hoverMoveEvent(event)

    def mouseDoubleClickEvent(self, event):
        if self.editor is not None:
            self.editor.rename_item_dialog(self.model_id)
        event.accept()

    def contextMenuEvent(self, event):
        if self.editor is not None:
            self.editor.show_item_context_menu(self, event.screenPos())
            event.accept()
            return
        super().contextMenuEvent(event)

    def mousePressEvent(self, event):
        if event.modifiers() & Qt.ControlModifier and self.editor is not None:
            self.editor.handle_ctrl_link_click(self.model_id)
            event.accept()
            return
        if self._handle_rect().contains(event.pos()):
            self._resizing = True
            self._resize_origin = event.pos()
            self._start_rect = QRectF(self.rect())
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._resizing:
            delta = event.pos() - self._resize_origin
            min_w, min_h = (42.0, 26.0) if self.item_type in CONNECTION_TYPES else (120.0, 56.0)
            w = max(min_w, self._start_rect.width() + delta.x())
            h = max(min_h, self._start_rect.height() + delta.y())
            self.prepareGeometryChange()
            self.setRect(0.0, 0.0, w, h)
            self._layout_text()
            if self.editor is not None:
                self.editor.on_node_resized(self.model_id, w, h)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._resizing = False
        super().mouseReleaseEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.GraphicsItemChange.ItemSelectedHasChanged:
            self._update_style(False)
        return super().itemChange(change, value)

    def connection_anchor(self, role: str) -> QPointF:
        rect = self.rect()
        center = self.sceneBoundingRect().center()
        if role == "from":
            return center + QPointF(rect.width() / 2.0 - 4.0, 0.0)
        if role == "to":
            return center + QPointF(-rect.width() / 2.0 + 4.0, 0.0)
        return center

    def paint(self, painter, option, widget=None):
        if self.item_type in CONNECTION_TYPES:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.setPen(self.pen())
            painter.setBrush(self.brush())
            rr = self.rect()
            radius = min(rr.height() * 0.45, 14.0)
            painter.drawRoundedRect(rr, radius, radius)
        else:
            super().paint(painter, option, widget)
        hr = self._handle_rect()
        painter.setPen(QPen(QColor("#e2e8f0"), 1.0))
        painter.setBrush(QColor("#0f172a"))
        painter.drawRect(hr)
class ConfigTextEdit(QTextEdit):
    editingFinished = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAcceptRichText(False)
        self.setTabChangesFocus(True)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.editingFinished.emit()


class TopologyScene(QGraphicsScene):
    selection_payload_changed = Signal(object)

    def __init__(self, editor: "TopologyConfigEditor"):
        super().__init__()
        self.editor = editor
        self.setSceneRect(-2000.0, -2000.0, 4000.0, 4000.0)
        self.selectionChanged.connect(self._emit_selection_payload)

    def _emit_selection_payload(self) -> None:
        items = self.selectedItems()
        if not items:
            self.selection_payload_changed.emit(None)
            return
        item = items[0]
        if isinstance(item, DiagramNodeItem):
            self.selection_payload_changed.emit({"kind": "node", "id": item.model_id, "type": item.item_type})
        else:
            self.selection_payload_changed.emit(None)

    def dragEnterEvent(self, event):
        if event.mimeData().hasFormat(MIME_PALETTE):
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasFormat(MIME_PALETTE):
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if not event.mimeData().hasFormat(MIME_PALETTE):
            super().dropEvent(event)
            return
        payload = json.loads(bytes(event.mimeData().data(MIME_PALETTE)).decode("utf-8"))
        pos = event.scenePos()
        self.editor.create_item_from_palette(payload["item_type"], pos)
        event.acceptProposedAction()


class TopologyGraphicsView(QGraphicsView):
    def __init__(self, scene: TopologyScene):
        super().__init__(scene)
        self._zoom_factor = 1.0
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setAcceptDrops(True)
        self.setBackgroundBrush(QColor("#0b1220"))

    def wheelEvent(self, event):
        self.apply_zoom(1.15 if event.angleDelta().y() > 0 else 1 / 1.15)

    def apply_zoom(self, factor: float) -> None:
        self.scale(factor, factor)
        self._zoom_factor *= factor

    def zoom_in(self) -> None:
        self.apply_zoom(1.15)

    def zoom_out(self) -> None:
        self.apply_zoom(1 / 1.15)

    def reset_zoom(self) -> None:
        self.resetTransform()
        self._zoom_factor = 1.0

    def fit_all(self) -> None:
        rect = self.scene().itemsBoundingRect()
        if rect.isValid() and rect.width() > 1.0 and rect.height() > 1.0:
            self.fitInView(rect.adjusted(-80.0, -80.0, 80.0, 80.0), Qt.AspectRatioMode.KeepAspectRatio)
            self._zoom_factor = self.transform().m11()

    def center_on_selection(self) -> None:
        items = self.scene().selectedItems()
        if items:
            self.centerOn(items[0])


class PaletteTree(QTreeWidget):
    add_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self.setSelectionMode(QTreeWidget.SelectionMode.SingleSelection)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self._build()
        self.expandAll()

    def _build(self) -> None:
        volumes = QTreeWidgetItem(["Volumen"])
        cylinders = QTreeWidgetItem(["Zylinder"])
        cylinders.setData(0, Qt.ItemDataRole.UserRole, {"item_type": "cylinder"})
        plenums = QTreeWidgetItem(["Behälter"])
        plenums.setData(0, Qt.ItemDataRole.UserRole, {"item_type": "plenum"})
        bounce_chambers = QTreeWidgetItem(["Bounce-Chambers"])
        bounce_chambers.setData(0, Qt.ItemDataRole.UserRole, {"item_type": "bounce_chamber"})
        environments = QTreeWidgetItem(["Umgebungen"])
        environments.setData(0, Qt.ItemDataRole.UserRole, {"item_type": "environment"})
        volumes.addChildren([cylinders, plenums, bounce_chambers, environments])

        throttles = QTreeWidgetItem(["Drosseln"])
        valves = QTreeWidgetItem(["Ventile"])
        valves.setData(0, Qt.ItemDataRole.UserRole, {"item_type": "valve"})
        slots = QTreeWidgetItem(["Slots"])
        slots.setData(0, Qt.ItemDataRole.UserRole, {"item_type": "slot"})
        orifices = QTreeWidgetItem(["Drosseln / Orifices"])
        orifices.setData(0, Qt.ItemDataRole.UserRole, {"item_type": "orifice"})
        check_valves = QTreeWidgetItem(["Rueckschlagventile"])
        check_valves.setData(0, Qt.ItemDataRole.UserRole, {"item_type": "check_valve"})
        throttles.addChildren([slots, valves, orifices, check_valves])

        self.addTopLevelItems([volumes, throttles])

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if item is None:
            return
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if not payload:
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(MIME_PALETTE, json.dumps(payload).encode("utf-8"))
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int) -> None:
        payload = item.data(0, Qt.ItemDataRole.UserRole)
        if payload:
            self.add_requested.emit(str(payload.get("item_type", "")))


class NodeListPanel(QWidget):
    selection_requested = Signal(str)
    add_requested = Signal(str)

    def __init__(self):
        super().__init__()
        self._records: list[dict[str, str]] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText("Elemente filtern …")
        self.search_edit.textChanged.connect(self._rebuild)
        layout.addWidget(self.search_edit)

        quick = QHBoxLayout()
        for text_label, item_type in (
            ("+ Zyl", "cylinder"),
            ("+ Beh", "plenum"),
            ("+ Bou", "bounce_chamber"),
            ("+ Umg", "environment"),
            ("+ Vent", "valve"),
            ("+ Slot", "slot"),
            ("+ Dros", "orifice"),
            ("+ Rueck", "check_valve"),
        ):
            btn = QPushButton(text_label)
            btn.setToolTip(f"{item_type} in der aktuellen Ansicht einfuegen")
            btn.clicked.connect(lambda _=False, t=item_type: self.add_requested.emit(t))
            quick.addWidget(btn)
        layout.addLayout(quick)

        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        layout.addWidget(self.list_widget)

        self.info_label = QLabel("0 Elemente")
        self.info_label.setStyleSheet("color:#94a3b8;")
        layout.addWidget(self.info_label)

    def refresh(self, volumes: list[dict[str, Any]], connections: list[dict[str, Any]], selected_id: str | None = None) -> None:
        self._records = []
        for group_name, models in (("Volumen", volumes), ("Verbindungen", connections)):
            for model in models:
                self._records.append({
                    "id": str(model.get("name", "")),
                    "type": str(model.get("type", "")),
                    "group": group_name,
                    "subtitle": str(model.get("from_volume", "")) + (" -> " + str(model.get("to_volume", "")) if model.get("type") in CONNECTION_TYPES else ""),
                })
        self._rebuild()
        if selected_id:
            self.select_id(selected_id)

    def _rebuild(self) -> None:
        filter_text = self.search_edit.text().strip().lower()
        current = self.current_id()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        visible_count = 0
        for record in self._records:
            hay = f"{record['id']} {record['type']} {record['group']} {record['subtitle']}".lower()
            if filter_text and filter_text not in hay:
                continue
            item = QListWidgetItem(f"[{record['type']}] {record['id']}")
            item.setData(Qt.ItemDataRole.UserRole, record['id'])
            item.setToolTip(f"{record['group']}\n{record['subtitle']}")
            self.list_widget.addItem(item)
            visible_count += 1
        self.list_widget.blockSignals(False)
        self.info_label.setText(f"{visible_count} / {len(self._records)} Elemente")
        if current:
            self.select_id(current)

    def current_id(self) -> str | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        return str(item.data(Qt.ItemDataRole.UserRole))

    def select_id(self, model_id: str) -> None:
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if str(item.data(Qt.ItemDataRole.UserRole)) == model_id:
                self.list_widget.setCurrentItem(item)
                break
        self.list_widget.blockSignals(False)

    def _on_selection_changed(self) -> None:
        model_id = self.current_id()
        if model_id:
            self.selection_requested.emit(model_id)


class ProblemPanel(QWidget):
    selection_requested = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.summary_label = QLabel("Keine Probleme")
        self.summary_label.setStyleSheet("font-weight:700;color:#86efac;")
        layout.addWidget(self.summary_label)

        self.list_widget = QListWidget()
        self.list_widget.itemActivated.connect(self._activate_item)
        self.list_widget.itemDoubleClicked.connect(self._activate_item)
        layout.addWidget(self.list_widget)

        hint = QLabel("Doppelklick springt zum betroffenen Element.")
        hint.setStyleSheet("color:#94a3b8;")
        layout.addWidget(hint)

    def refresh(self, problems: list[dict[str, str]]) -> None:
        self.list_widget.clear()
        if not problems:
            self.summary_label.setText("Keine Probleme")
            self.summary_label.setStyleSheet("font-weight:700;color:#86efac;")
            return
        errors = sum(1 for p in problems if p.get("severity") == "Fehler")
        warnings = len(problems) - errors
        parts = []
        if errors:
            parts.append(f"{errors} Fehler")
        if warnings:
            parts.append(f"{warnings} Hinweise")
        self.summary_label.setText(", ".join(parts))
        self.summary_label.setStyleSheet("font-weight:700;color:#fbbf24;")
        for problem in problems:
            item = QListWidgetItem(f"{problem.get('severity', 'Hinweis')}: {problem.get('text', '')}")
            item.setData(Qt.ItemDataRole.UserRole, problem.get("model_id", ""))
            item.setToolTip(problem.get("detail", problem.get("text", "")))
            self.list_widget.addItem(item)

    def _activate_current(self) -> None:
        item = self.list_widget.currentItem()
        if item is None:
            return
        self._activate_item(item)

    def _activate_item(self, item: QListWidgetItem) -> None:
        model_id = str(item.data(Qt.ItemDataRole.UserRole) or "")
        if model_id:
            self.selection_requested.emit(model_id)


SUBMODEL_LIBRARY_TYPES = ("wall_heat", "wall_temperature", "combustion", "ignition", "evaporation")
SUBMODEL_LABELS = {
    "wall_heat": "Wandwaerme",
    "wall_temperature": "Wandtemperatur",
    "combustion": "Verbrennung",
    "ignition": "Zuendung",
    "evaporation": "Verdampfung",
}


class SubmodelLibraryPanel(QWidget):
    selection_requested = Signal(str, str)
    add_requested = Signal(str)
    apply_requested = Signal(str, str)
    delete_requested = Signal(str, str)

    def __init__(self):
        super().__init__()
        self._records: list[dict[str, str]] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.search_edit = QLineEdit()
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.setPlaceholderText("Submodelle filtern ...")
        self.search_edit.textChanged.connect(self._rebuild)
        layout.addWidget(self.search_edit)

        quick = QHBoxLayout()
        for label, submodel_type in (
            ("+ Ww", "wall_heat"),
            ("+ Wt", "wall_temperature"),
            ("+ Verbr", "combustion"),
            ("+ Zuend", "ignition"),
            ("+ Verd", "evaporation"),
        ):
            btn = QPushButton(label)
            btn.setToolTip(f"{SUBMODEL_LABELS[submodel_type]}-Submodell anlegen")
            btn.clicked.connect(lambda _=False, t=submodel_type: self.add_requested.emit(t))
            quick.addWidget(btn)
        layout.addLayout(quick)

        self.list_widget = QListWidget()
        self.list_widget.itemSelectionChanged.connect(self._on_selection_changed)
        self.list_widget.itemDoubleClicked.connect(self._on_item_activated)
        layout.addWidget(self.list_widget)

        buttons = QHBoxLayout()
        self.apply_button = QPushButton("Auf Volumen anwenden")
        self.apply_button.clicked.connect(self._apply_current)
        buttons.addWidget(self.apply_button)
        self.delete_button = QPushButton("Loeschen")
        self.delete_button.clicked.connect(self._delete_current)
        buttons.addWidget(self.delete_button)
        layout.addLayout(buttons)

        self.info_label = QLabel("0 Submodelle")
        self.info_label.setStyleSheet("color:#94a3b8;")
        layout.addWidget(self.info_label)

    def refresh(self, submodels: dict[str, Any], selected: tuple[str, str] | None = None) -> None:
        self._records = []
        for submodel_type in SUBMODEL_LIBRARY_TYPES:
            group = submodels.get(submodel_type, {})
            if not isinstance(group, dict):
                continue
            for name, data in group.items():
                model_kind = ""
                if isinstance(data, dict):
                    model_kind = str(data.get("model", data.get("type", "")) or "")
                self._records.append({
                    "type": submodel_type,
                    "name": str(name),
                    "label": SUBMODEL_LABELS.get(submodel_type, submodel_type),
                    "model": model_kind,
                })
        self._rebuild()
        if selected is not None:
            self.select_id(selected[0], selected[1])

    def _rebuild(self) -> None:
        filter_text = self.search_edit.text().strip().lower()
        current = self.current_id()
        self.list_widget.blockSignals(True)
        self.list_widget.clear()
        visible_count = 0
        for record in self._records:
            hay = f"{record['type']} {record['label']} {record['name']} {record['model']}".lower()
            if filter_text and filter_text not in hay:
                continue
            suffix = f" ({record['model']})" if record["model"] else ""
            item = QListWidgetItem(f"[{record['label']}] {record['name']}{suffix}")
            item.setData(Qt.ItemDataRole.UserRole, (record["type"], record["name"]))
            self.list_widget.addItem(item)
            visible_count += 1
        self.list_widget.blockSignals(False)
        self.info_label.setText(f"{visible_count} / {len(self._records)} Submodelle")
        if current is not None:
            self.select_id(current[0], current[1])

    def current_id(self) -> tuple[str, str] | None:
        item = self.list_widget.currentItem()
        if item is None:
            return None
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and len(data) == 2:
            return str(data[0]), str(data[1])
        return None

    def select_id(self, submodel_type: str, name: str) -> None:
        self.list_widget.blockSignals(True)
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, tuple) and data == (submodel_type, name):
                self.list_widget.setCurrentItem(item)
                break
        self.list_widget.blockSignals(False)

    def _on_selection_changed(self) -> None:
        current = self.current_id()
        if current is not None:
            self.selection_requested.emit(current[0], current[1])

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, tuple) and len(data) == 2:
            self.selection_requested.emit(str(data[0]), str(data[1]))

    def _apply_current(self) -> None:
        current = self.current_id()
        if current is not None:
            self.apply_requested.emit(current[0], current[1])

    def _delete_current(self) -> None:
        current = self.current_id()
        if current is not None:
            self.delete_requested.emit(current[0], current[1])


class PropertyPanel(QWidget):
    value_changed = Signal(str, object)

    def __init__(self):
        super().__init__()
        self._payload: dict[str, Any] | None = None
        self._data: dict[str, Any] | None = None
        self._widgets: dict[str, QWidget] = {}
        self._row_containers: dict[str, QWidget] = {}
        self._row_labels: dict[str, QWidget] = {}
        self._row_forms: dict[str, QFormLayout] = {}
        self._tab_forms: dict[str, QFormLayout] = {}
        self._submodel_refs: dict[str, list[str]] = {}
        self._updating = False

        self.layout_main = QVBoxLayout(self)
        self.layout_main.setContentsMargins(8, 8, 8, 8)
        self.layout_main.setSpacing(8)
        self.title_label = QLabel("Eigenschaften")
        self.title_label.setStyleSheet("font-weight:700;font-size:14px;")
        self.layout_main.addWidget(self.title_label)

        self.tabs = QTabWidget()
        self.layout_main.addWidget(self.tabs)
        self.empty_label = QLabel("Kein Element ausgewählt.")
        self.empty_label.setStyleSheet("color:#94a3b8;")
        self.layout_main.addWidget(self.empty_label)
        self.schema_label = QLabel("")
        self.schema_label.setWordWrap(True)
        self.schema_label.setStyleSheet("color:#93c5fd;background:#0f172a;border:1px solid #1e3a8a;border-radius:6px;padding:8px;")
        self.layout_main.addWidget(self.schema_label)
        self.schema_label.hide()

    def clear_fields(self) -> None:
        self.tabs.clear()
        self._widgets.clear()
        self._row_containers.clear()
        self._row_labels.clear()
        self._row_forms.clear()
        self._tab_forms.clear()

    def _ensure_tab_form(self, tab_name: str) -> QFormLayout:
        name = tab_name or "Allgemein"
        if name in self._tab_forms:
            return self._tab_forms[name]
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        frame = QWidget()
        form = QFormLayout(frame)
        form.setContentsMargins(8, 8, 8, 8)
        form.setSpacing(8)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        scroll.setWidget(frame)
        self.tabs.addTab(scroll, name)
        self._tab_forms[name] = form
        return form

    def _tab_name_for_key(self, key: str) -> str:
        if key == "name" or key.startswith(("initial_", "kinematics.", "fixed_volume_", "pressure_", "temperature_")):
            return "Allgemein"
        if key.startswith("combustion.ignition."):
            return "Ignition"
        if key.startswith("combustion."):
            return "Combustion"
        if key.startswith(("wall_heat.", "wall_temperature.")):
            return "Waerme"
        if key.startswith("evaporation."):
            return "Evaporation"
        if key in {"from_volume", "to_volume"} or key.startswith(("opening_", "distance_", "width_", "height_", "discharge_", "area_", "diameter_", "cracking_", "lift_", "alpha_", "lash_", "source_", "piston_", "entrance_", "open_", "full_", "number_", "forward_", "reverse_")):
            return "Verbindung"
        return "Sonstiges"

    def set_payload(self, title: str, payload: dict[str, Any] | None, data: dict[str, Any] | None, volume_names: list[str], submodel_refs: dict[str, list[str]] | None = None):
        self._payload = payload
        self._data = data
        self._submodel_refs = submodel_refs or {}
        self.title_label.setText(title)
        self.clear_fields()
        if payload is None or data is None:
            self.empty_label.show()
            self.schema_label.hide()
            return
        self.empty_label.hide()
        schema_summary = build_context_summary(payload)
        if schema_summary:
            self.schema_label.setText(schema_summary)
            self.schema_label.show()
        else:
            self.schema_label.hide()
        specs = self._field_specs(payload, data, volume_names)
        self._ensure_defaults_for_specs(specs)
        for spec in specs:
            self._add_field(spec)
        self._apply_dynamic_visibility()

    def _meta_spec(self, key: str, **overrides: Any) -> dict[str, Any]:
        meta = meta_for(key)
        if meta is None:
            spec = {"key": key, "label": key, "type": overrides.pop("type", "text")}
            spec.update(overrides)
            return spec
        spec: dict[str, Any] = {"key": key, "label": meta.label, "type": meta.kind}
        if meta.choices:
            spec["choices"] = list(meta.choices)
        if meta.visible_if is not None:
            spec["visible_if"] = meta.visible_if
        if meta.help_text:
            spec["help"] = meta.help_text
        if meta.default is not None:
            spec["default"] = meta.default
        spec.update(overrides)
        return spec

    def _optional_alt_spec(self, key: str, **overrides: Any) -> dict[str, Any]:
        spec = self._meta_spec(key, **overrides)
        spec.pop("default", None)
        return spec

    def _ensure_defaults_for_specs(self, specs: list[dict[str, Any]]) -> None:
        for spec in specs:
            key = spec.get("key")
            if not key or self._get_value(key) is not None:
                continue
            if "visible_if" in spec and not self._visible_if_matches(spec["visible_if"]):
                continue
            if "default" in spec:
                default = spec["default"]
                if str(key).endswith(".duration_mode") and self._get_value("combustion.model") == "hcci_diesel":
                    default = "time"
                self._set_value(key, default)

    def _field_specs(self, payload: dict[str, Any], data: dict[str, Any], volume_names: list[str]) -> list[dict[str, Any]]:
        kind = payload.get("kind")
        item_type = payload.get("type")
        if kind == "root":
            return self._root_specs(data)
        if kind == "submodel":
            return self._with_remaining_specs(self._submodel_library_specs(str(item_type), data), data)
        if item_type == "cylinder":
            return self._with_remaining_specs(self._cylinder_specs(data), data)
        if item_type == "plenum":
            return self._with_remaining_specs(self._plenum_specs(data), data)
        if item_type == "bounce_chamber":
            return self._with_remaining_specs(self._bounce_chamber_specs(data), data)
        if item_type == "environment":
            return self._with_remaining_specs(self._environment_specs(data), data)
        if item_type == "valve":
            return self._with_remaining_specs(self._valve_specs(data, volume_names), data)
        if item_type == "slot":
            return self._with_remaining_specs(self._slot_specs(data, volume_names), data)
        if item_type == "orifice":
            return self._with_remaining_specs(self._orifice_specs(data, volume_names), data)
        if item_type == "check_valve":
            return self._with_remaining_specs(self._check_valve_specs(data, volume_names), data)
        return []

    def _submodel_library_specs(self, submodel_type: str, data: dict[str, Any]) -> list[dict[str, Any]]:
        if submodel_type == "wall_heat":
            return self._direct_submodel_specs("wall_heat")
        if submodel_type == "wall_temperature":
            return self._direct_submodel_specs("wall_temperature")
        if submodel_type == "combustion":
            return self._direct_submodel_specs("combustion", include_angle_reference=True)
        if submodel_type == "ignition":
            return self._direct_submodel_specs("ignition")
        if submodel_type == "evaporation":
            return self._direct_submodel_specs("evaporation", include_angle_reference=True)
        return []

    def _volume_submodel_specs(self, prefix: str, include_angle_reference: bool = False) -> list[dict[str, Any]]:
        refs = self._submodel_refs.get(prefix, [])
        specs: list[dict[str, Any]] = []
        if refs:
            specs.append(self._meta_spec(f"{prefix}.ref", type="choice", choices=["", *refs], label=f"{SUBMODEL_LABELS.get(prefix, prefix)} ref", tab=self._tab_name_for_key(f"{prefix}.ref")))
        submodel_specs = self._submodel_specs(prefix, include_angle_reference=include_angle_reference)
        if prefix == "combustion":
            diagnostics_refs = sorted({*self._submodel_refs.get("ignition", []), *self._submodel_refs.get("combustion", [])})
            if diagnostics_refs:
                for spec in submodel_specs:
                    if spec.get("key") == "combustion.hcci_diagnostics_ref":
                        spec["type"] = "choice"
                        spec["choices"] = ["", *diagnostics_refs]
                        break
        return specs + submodel_specs

    def _direct_submodel_specs(self, prefix: str, include_angle_reference: bool = False) -> list[dict[str, Any]]:
        direct_specs: list[dict[str, Any]] = []
        marker = f"{prefix}."
        for spec in self._submodel_specs(prefix, include_angle_reference=include_angle_reference):
            key = str(spec.get("key", ""))
            if not key.startswith(marker):
                continue
            direct = dict(spec)
            direct["key"] = key[len(marker):]
            if "visible_if" in direct:
                direct["visible_if"] = self._strip_visible_if_prefix(direct["visible_if"], marker)
            direct_specs.append(direct)
        return direct_specs

    def _strip_visible_if_prefix(self, condition: Any, marker: str) -> Any:
        if isinstance(condition, tuple) and len(condition) == 2 and isinstance(condition[0], str):
            dep_key = condition[0]
            if dep_key.startswith(marker):
                dep_key = dep_key[len(marker):]
            return dep_key, condition[1]
        if isinstance(condition, list):
            return [self._strip_visible_if_prefix(item, marker) for item in condition]
        if isinstance(condition, dict):
            return {key: self._strip_visible_if_prefix(value, marker) if isinstance(value, (tuple, list, dict)) else value for key, value in condition.items()}
        return condition

    def _with_remaining_specs(self, specs: list[dict[str, Any]], data: dict[str, Any]) -> list[dict[str, Any]]:
        existing = {str(spec.get("key", "")) for spec in specs}
        result = list(specs)
        for key, value in self._iter_editable_leaf_values(data):
            if key in existing:
                continue
            if key.startswith("combustion."):
                continue
            result.append(self._meta_spec(key, label=key, type=self._kind_for_value(value)))
            existing.add(key)
        return result

    def _iter_editable_leaf_values(self, data: dict[str, Any], prefix: str = ""):
        for key, value in data.items():
            dotted = f"{prefix}.{key}" if prefix else str(key)
            if dotted == "type" or dotted.endswith(".type"):
                continue
            if isinstance(value, dict):
                yield from self._iter_editable_leaf_values(value, dotted)
            else:
                yield dotted, value

    def _kind_for_value(self, value: Any) -> str:
        if isinstance(value, bool):
            return "bool"
        if isinstance(value, int) and not isinstance(value, bool):
            return "int"
        if isinstance(value, float) or value is None:
            return "float"
        if isinstance(value, (list, dict)):
            return "yaml"
        return "text"

    def _root_specs(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        data.setdefault("simulation", {})
        data.setdefault("postprocessing", {})
        data.setdefault("preprocessing", {})
        return [
            self._meta_spec("test_description"),
            self._meta_spec("preprocessing.gas_properties.cp_J_per_kgK"),
            self._meta_spec("preprocessing.gas_properties.cv_J_per_kgK"),
            self._meta_spec("preprocessing.gas_properties.R_J_per_kgK"),
            self._meta_spec("preprocessing.gas_properties.thermo_model"),
            self._meta_spec("preprocessing.features.mass_flow"),
            self._meta_spec("preprocessing.features.wall_heat"),
            self._meta_spec("preprocessing.features.combustion"),
            self._meta_spec("preprocessing.features.evaporation"),
            self._meta_spec("preprocessing.features.pv_work"),
            self._meta_spec("preprocessing.engine.cycle_type"),
            self._meta_spec("preprocessing.engine.speed_rpm"),
            self._meta_spec("simulation.dt_s"),
            self._meta_spec("simulation.total_cycles"),
            self._meta_spec("simulation.save_last_cycles"),
            self._meta_spec("simulation.simulationtime"),
            self._meta_spec("simulation.solver.kind", choices=list(SOLVER_KINDS)),
            self._meta_spec("simulation.solver.rtol"),
            self._meta_spec("simulation.solver.atol"),
            self._meta_spec("postprocessing.csv_enabled"),
            self._meta_spec("postprocessing.mode", choices=("pipeline",)),
            self._meta_spec("postprocessing.config"),
            self._meta_spec("postprocessing.csv_path"),
            self._meta_spec("postprocessing.csv_separator"),
            self._meta_spec("postprocessing.csv_export_layout"),
            self._meta_spec("postprocessing.csv_export_mode"),
            self._meta_spec("postprocessing.csv_export_missing_layout"),
            self._meta_spec("postprocessing.csv_export_unknown_signals"),
            self._meta_spec("postprocessing.excel_enabled"),
            self._meta_spec("postprocessing.excel_path"),
            self._meta_spec("postprocessing.sampling.mode", choices=list(SAMPLING_MODES)),
            self._meta_spec("postprocessing.sampling.step_s"),
            self._meta_spec("postprocessing.sampling.step_deg"),
            self._meta_spec("postprocessing.final_cycle_uniform_angle_export.enabled"),
            self._meta_spec("postprocessing.final_cycle_uniform_angle_export.step_deg"),
            self._meta_spec("postprocessing.free_piston_last_ut_ot_ut_export.enabled"),
            self._meta_spec("postprocessing.free_piston_last_ut_ot_ut_export.step_deg"),
            self._meta_spec("postprocessing.free_piston_last_ut_ot_ut_export.axis_min_deg"),
            self._meta_spec("postprocessing.free_piston_last_ut_ot_ut_export.axis_max_deg"),
            self._meta_spec("postprocessing.check_report.enabled"),
            self._meta_spec("postprocessing.check_report.html_enabled"),
            self._meta_spec("postprocessing.plots.enabled"),
            self._meta_spec("postprocessing.plots.source", choices=list(PLOT_SOURCES)),
            self._meta_spec("postprocessing.plots.output_dir"),
            self._meta_spec("postprocessing.plots.layouts.auto_create_defaults"),
            self._meta_spec("postprocessing.plots.layouts.entries"),
            self._meta_spec("postprocessing.console.run_summary.enabled"),
            self._meta_spec("postprocessing.console.cycle_summary.enabled"),
            self._meta_spec("postprocessing.console.check_report.enabled"),
            self._meta_spec("postprocessing.console.geometry.enabled"),
        ]

    def _submodel_specs(self, prefix: str, include_angle_reference: bool = False) -> list[dict[str, Any]]:
        if prefix.endswith("wall_heat"):
            return [
                self._meta_spec(f"{prefix}.model"),
                self._meta_spec(f"{prefix}.variant"),
                self._meta_spec(f"{prefix}.wall_temperature_K"),
                self._meta_spec(f"{prefix}.wall_area_m2"),
                self._meta_spec(f"{prefix}.multiplier"),
                self._meta_spec(f"{prefix}.dp_mode"),
                self._meta_spec(f"{prefix}.reference_state_mode"),
                self._meta_spec(f"{prefix}.phase_mode"),
                self._meta_spec(f"{prefix}.c1"),
                self._meta_spec(f"{prefix}.c2"),
                self._meta_spec(f"{prefix}.c3"),
                self._meta_spec(f"{prefix}.cucm"),
                self._meta_spec(f"{prefix}.swirl_number"),
                self._meta_spec(f"{prefix}.imep_bar"),
            ]
        if prefix.endswith("wall_temperature"):
            return [
                self._meta_spec(f"{prefix}.model"),
                self._meta_spec(f"{prefix}.relaxation"),
                self._meta_spec(f"{prefix}.cylinder.initial_temperature_K"),
                self._meta_spec(f"{prefix}.cylinder.coolant_temperature_K"),
                self._meta_spec(f"{prefix}.cylinder.lambda_W_per_mK"),
                self._meta_spec(f"{prefix}.cylinder.wall_thickness_m"),
                self._meta_spec(f"{prefix}.cylinder.area_m2"),
                self._meta_spec(f"{prefix}.head.initial_temperature_K"),
                self._meta_spec(f"{prefix}.head.coolant_temperature_K"),
                self._meta_spec(f"{prefix}.head.lambda_W_per_mK"),
                self._meta_spec(f"{prefix}.head.wall_thickness_m"),
                self._meta_spec(f"{prefix}.head.area_m2"),
                self._meta_spec(f"{prefix}.piston.initial_temperature_K"),
                self._meta_spec(f"{prefix}.piston.coolant_temperature_K"),
                self._meta_spec(f"{prefix}.piston.lambda_W_per_mK"),
                self._meta_spec(f"{prefix}.piston.wall_thickness_m"),
                self._meta_spec(f"{prefix}.piston.area_m2"),
            ]
        if prefix.endswith("combustion"):
            specs = [
                self._meta_spec(f"{prefix}.model", tab="Combustion"),
                self._meta_spec(f"{prefix}.start_mode", tab="Combustion"),
                self._meta_spec(f"{prefix}.start_deg", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.start_mode", "angle")], tab="Combustion"),
                self._meta_spec(f"{prefix}.start_hub_m", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.start_mode", "compression_hub")], tab="Combustion"),
                self._meta_spec(f"{prefix}.hign_m", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.start_mode", "hign_position")], tab="Combustion"),
                self._meta_spec(f"{prefix}.hign_mm", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.start_mode", "hign_position")], tab="Combustion"),
                self._meta_spec(f"{prefix}.hign_m", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.start_mode", "expansion_distance_from_tdc")], tab="Combustion"),
                self._meta_spec(f"{prefix}.hign_mm", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.start_mode", "expansion_distance_from_tdc")], tab="Combustion"),
                self._meta_spec(f"{prefix}.duration_mode", visible_if=(f"{prefix}.model", ("vibe", "hcci_diesel")), tab="Combustion"),
                self._meta_spec(f"{prefix}.duration_deg", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.duration_mode", "angle")], tab="Combustion"),
                self._meta_spec(f"{prefix}.duration_hub_m", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.duration_mode", "compression_hub")], tab="Combustion"),
                self._meta_spec(f"{prefix}.duration_s", visible_if=(f"{prefix}.duration_mode", "time"), tab="Combustion"),
                self._meta_spec(f"{prefix}.duration_ms", visible_if=(f"{prefix}.duration_mode", "time"), tab="Combustion"),
                self._meta_spec(f"{prefix}.a", visible_if=(f"{prefix}.model", ("vibe", "hcci_diesel")), tab="Combustion"),
                self._meta_spec(f"{prefix}.m", visible_if=(f"{prefix}.model", ("vibe", "hcci_diesel")), tab="Combustion"),
                self._meta_spec(f"{prefix}.fueling_mode", type="choice", choices=["fixed_energy", "lambda_from_cylinder_mass_at_slot_close", "lambda_from_cylinder_air_at_slot_close_vapor_injector"], visible_if=(f"{prefix}.model", "vibe"), tab="Combustion"),
                self._meta_spec(f"{prefix}.fuel_mass_per_cycle_kg", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.fueling_mode", "fixed_energy")], tab="Combustion"),
                self._meta_spec(f"{prefix}.added_energy_per_cycle_J", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.fueling_mode", "fixed_energy")], tab="Combustion"),
                self._meta_spec(f"{prefix}.lambda_target", visible_if={"any": [(f"{prefix}.model", "hcci_diesel"), [(f"{prefix}.model", "vibe"), (f"{prefix}.fueling_mode", ("lambda_from_cylinder_mass_at_slot_close", "lambda_from_cylinder_air_at_slot_close_vapor_injector"))]]}, tab="Combustion"),
                self._meta_spec(f"{prefix}.lhv_J_per_kg", visible_if=(f"{prefix}.model", ("vibe", "hcci_diesel")), tab="Combustion"),
                self._meta_spec(f"{prefix}.afr_stoich_kg_air_per_kg_fuel", visible_if=(f"{prefix}.model", ("vibe", "hcci_diesel")), tab="Combustion"),
                self._meta_spec(f"{prefix}.combustion_efficiency_0to1", visible_if=(f"{prefix}.model", ("vibe", "hcci_diesel")), tab="Combustion"),
                self._meta_spec(f"{prefix}.injection_duration_s", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.fueling_mode", "lambda_from_cylinder_air_at_slot_close_vapor_injector")], tab="Combustion"),
                self._meta_spec(f"{prefix}.injection_duration_ms", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.fueling_mode", "lambda_from_cylinder_air_at_slot_close_vapor_injector")], tab="Combustion"),
                self._meta_spec(f"{prefix}.energy_coupling", visible_if=(f"{prefix}.model", "vibe"), tab="Combustion"),
                self._meta_spec(f"{prefix}.stroke_reference_m", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.energy_coupling", "stroke_ratio")], tab="Combustion"),
                self._meta_spec(f"{prefix}.stroke_exponent", visible_if=[(f"{prefix}.model", "vibe"), (f"{prefix}.energy_coupling", "stroke_ratio")], tab="Combustion"),
                self._meta_spec(f"{prefix}.slot_open_threshold_m2", visible_if=(f"{prefix}.model", ("vibe", "hcci_diesel")), tab="Combustion"),
                self._meta_spec(f"{prefix}.slot_closed_threshold_m2", visible_if=(f"{prefix}.model", ("vibe", "hcci_diesel")), tab="Combustion"),
                self._meta_spec(f"{prefix}.compression_velocity_threshold_m_per_s", visible_if=(f"{prefix}.model", ("vibe", "hcci_diesel")), tab="Combustion"),
                self._meta_spec(f"{prefix}.hcci_diagnostics_ref", visible_if=(f"{prefix}.model", "vibe"), tab="Combustion"),
                self._meta_spec(f"{prefix}.burn_model", visible_if=(f"{prefix}.model", "hcci_diesel"), tab="Combustion"),
                self._meta_spec(f"{prefix}.ignition.model", visible_if=(f"{prefix}.model", "hcci_diesel"), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.ignition_delay_table_npz", visible_if=(f"{prefix}.ignition.model", "tabulated_livengood_wu"), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.tau_A_s", visible_if=(f"{prefix}.ignition.model", ("livengood_wu", "tabulated_livengood_wu")), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.tau_pressure_exponent", visible_if=(f"{prefix}.ignition.model", ("livengood_wu", "tabulated_livengood_wu")), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.tau_activation_temperature_K", visible_if=(f"{prefix}.ignition.model", ("livengood_wu", "tabulated_livengood_wu", "beck_2003_1_arrhenius", "beck_2003_two_stage")), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.tau_activation_energy_J_per_kg", visible_if=(f"{prefix}.ignition.model", ("livengood_wu", "tabulated_livengood_wu", "beck_2003_1_arrhenius", "beck_2003_two_stage")), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.tau_reference_pressure_Pa", visible_if=(f"{prefix}.ignition.model", ("livengood_wu", "tabulated_livengood_wu", "beck_2003_1_arrhenius", "beck_2003_two_stage")), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.tau_reference_lambda", visible_if=(f"{prefix}.ignition.model", ("livengood_wu", "tabulated_livengood_wu", "beck_2003_1_arrhenius", "beck_2003_two_stage")), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.lambda_slowdown_exponent", visible_if=(f"{prefix}.model", "hcci_diesel"), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.residual_slowdown_factor", visible_if=(f"{prefix}.model", "hcci_diesel"), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.beck_c1_s", visible_if=(f"{prefix}.ignition.model", ("beck_2003_1_arrhenius", "beck_2003_two_stage")), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.beck_c2", visible_if=(f"{prefix}.ignition.model", ("beck_2003_1_arrhenius", "beck_2003_two_stage")), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.beck_reference_pressure_bar", visible_if=(f"{prefix}.ignition.model", ("beck_2003_1_arrhenius", "beck_2003_two_stage")), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.beck_reference_o2_percent", visible_if=(f"{prefix}.ignition.model", ("beck_2003_1_arrhenius", "beck_2003_two_stage")), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.beck_cf_fuel_name", visible_if=(f"{prefix}.ignition.model", "beck_2003_two_stage"), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.cool_flame_enabled", visible_if=(f"{prefix}.ignition.model", "beck_2003_two_stage"), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.cool_flame_burn_model", visible_if=[(f"{prefix}.ignition.model", "beck_2003_two_stage"), (f"{prefix}.ignition.cool_flame_enabled", True)], tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.cool_flame_energy_fraction", visible_if=[(f"{prefix}.ignition.model", "beck_2003_two_stage"), (f"{prefix}.ignition.cool_flame_enabled", True)], tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.cool_flame_duration_ms", visible_if=[(f"{prefix}.ignition.model", "beck_2003_two_stage"), (f"{prefix}.ignition.cool_flame_enabled", True)], tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.start_temperature_min_K", visible_if=(f"{prefix}.model", "hcci_diesel"), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.start_pressure_min_Pa", visible_if=(f"{prefix}.model", "hcci_diesel"), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.max_ignition_delay_s", visible_if=(f"{prefix}.model", "hcci_diesel"), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.accumulation_start_mode", visible_if=(f"{prefix}.model", "hcci_diesel"), tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.accumulation_start_distance_from_tdc_mm", visible_if=[(f"{prefix}.model", "hcci_diesel"), (f"{prefix}.ignition.accumulation_start_mode", "piston_distance_from_tdc")], tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.accumulation_start_distance_from_tdc_m", visible_if=[(f"{prefix}.model", "hcci_diesel"), (f"{prefix}.ignition.accumulation_start_mode", "piston_distance_from_tdc")], tab="Ignition"),
                self._meta_spec(f"{prefix}.ignition.accumulation_end_mode", visible_if=(f"{prefix}.model", "hcci_diesel"), tab="Ignition"),
            ]
            if include_angle_reference:
                specs.append(self._meta_spec(f"{prefix}.angle_reference", choices=list(ANGLE_REFERENCES), visible_if=(f"{prefix}.model", "vibe"), tab="Combustion"))
            return specs
        specs = [
            self._meta_spec(f"{prefix}.model"),
            self._meta_spec(f"{prefix}.start_deg"),
            self._meta_spec(f"{prefix}.duration_deg"),
            self._meta_spec(f"{prefix}.evaporated_mass_per_cycle_kg"),
            self._meta_spec(f"{prefix}.latent_heat_J_per_kg"),
        ]
        if include_angle_reference:
            specs.append(self._meta_spec(f"{prefix}.angle_reference", choices=list(ANGLE_REFERENCES)))
        return specs

    def _cylinder_specs(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        specs = [
            self._meta_spec("name"),
            self._meta_spec("initial_pressure_Pa"),
            self._meta_spec("initial_mass_kg"),
            self._meta_spec("initial_temperature_K"),
            self._meta_spec("initial_burned_fraction_0to1"),
            self._meta_spec("initial_burned_mass_percent"),
            self._meta_spec("kinematics.bore_m"),
            self._meta_spec("kinematics.stroke_m"),
            self._meta_spec("kinematics.conrod_m"),
            self._meta_spec("kinematics.compression_ratio"),
            self._meta_spec("kinematics.phase_deg"),
        ]
        specs += self._volume_submodel_specs("wall_heat")
        specs += self._volume_submodel_specs("wall_temperature")
        specs += self._volume_submodel_specs("combustion", include_angle_reference=True)
        specs += self._volume_submodel_specs("evaporation", include_angle_reference=True)
        return specs

    def _plenum_specs(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        specs = [
            self._meta_spec("name"),
            self._meta_spec("initial_pressure_Pa"),
            self._meta_spec("initial_mass_kg"),
            self._meta_spec("initial_temperature_K"),
            self._meta_spec("initial_burned_fraction_0to1"),
            self._meta_spec("initial_burned_mass_percent"),
            self._meta_spec("fixed_volume_m3"),
        ]
        specs += self._volume_submodel_specs("wall_heat")
        specs += self._volume_submodel_specs("wall_temperature")
        specs += self._volume_submodel_specs("combustion", include_angle_reference=True)
        specs += self._volume_submodel_specs("evaporation", include_angle_reference=True)
        return specs

    def _environment_specs(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._meta_spec("name"),
            self._meta_spec("pressure_Pa"),
            self._meta_spec("temperature_K"),
        ]

    def _bounce_chamber_specs(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            self._meta_spec("name"),
            self._meta_spec("model", type="choice", choices=["gas_spring", "gas_exchange"], default="gas_spring"),
            self._meta_spec("initial_pressure_Pa"),
            self._meta_spec("initial_temperature_K"),
            self._meta_spec("initial_burned_fraction_0to1"),
            self._meta_spec("initial_burned_mass_percent"),
            self._meta_spec("chamber_diameter_m", type="float", default=0.0745, label="Bounce chamber diameter [m]"),
            self._meta_spec("chamber_length_m", type="float", default=0.08, label="Bounce chamber length [m]"),
            self._meta_spec("compression_ratio", type="float", default=2.5, label="Bounce compression ratio"),
            self._meta_spec("chamber_volume0_m3", type="float", default=None, label="Legacy chamber V0 [m3]"),
            self._meta_spec("p0_Pa", type="float", default=None, label="p0 [Pa]"),
            self._meta_spec("polytropic_exponent", type="float", default=1.3, label="Polytropic exponent"),
        ]

    def _valve_specs(self, data: dict[str, Any], volume_names: list[str]) -> list[dict[str, Any]]:
        return [
            self._meta_spec("name"),
            self._meta_spec("from_volume", choices=volume_names),
            self._meta_spec("to_volume", choices=volume_names),
            self._meta_spec("opening_angle_deg"),
            self._meta_spec("opening_reference", choices=list(ANGLE_REFERENCES)),
            self._meta_spec("profile_angle_domain", choices=list(PROFILE_ANGLE_DOMAINS)),
            self._meta_spec("lift_scale"),
            self._meta_spec("lash_m"),
            self._meta_spec("lift_file"),
            self._meta_spec("alpha_k_file"),
        ]

    def _slot_specs(self, data: dict[str, Any], volume_names: list[str]) -> list[dict[str, Any]]:
        return [
            self._meta_spec("name"),
            self._meta_spec("from_volume", choices=volume_names),
            self._meta_spec("to_volume", choices=volume_names),
            self._meta_spec("source_of_data"),
            self._meta_spec("opening_mode"),
            self._meta_spec("distance_from_tdc_m"),
            self._optional_alt_spec("distance_from_tdc_mm"),
            self._optional_alt_spec("opening_angle_deg"),
            self._meta_spec("piston_height_if_crankcase_m"),
            self._meta_spec("entrance_angle_deg"),
            self._meta_spec("width_m"),
            self._optional_alt_spec("width_mm"),
            self._meta_spec("height_m"),
            self._optional_alt_spec("height_mm"),
            self._meta_spec("open_fillet_radius_m"),
            self._meta_spec("full_fillet_radius_m"),
            self._meta_spec("number_of_identical_holes"),
            self._meta_spec("discharge_coefficients.mode"),
            self._meta_spec("discharge_coefficients.forward_cd"),
            self._meta_spec("discharge_coefficients.reverse_cd"),
            self._meta_spec("discharge_coefficients.table_file"),
        ]

    def _orifice_specs(self, data: dict[str, Any], volume_names: list[str]) -> list[dict[str, Any]]:
        return [
            self._meta_spec("name"),
            self._meta_spec("from_volume", choices=volume_names),
            self._meta_spec("to_volume", choices=volume_names),
            self._meta_spec("area_m2"),
            self._optional_alt_spec("diameter_mm"),
            self._meta_spec("forward_cd"),
            self._meta_spec("reverse_cd"),
        ]

    def _check_valve_specs(self, data: dict[str, Any], volume_names: list[str]) -> list[dict[str, Any]]:
        return [
            self._meta_spec("name"),
            self._meta_spec("from_volume", choices=volume_names),
            self._meta_spec("to_volume", choices=volume_names),
            self._meta_spec("area_m2"),
            self._optional_alt_spec("diameter_mm"),
            self._meta_spec("discharge_coefficient", type="float", default=0.7, label="Discharge coefficient"),
            self._meta_spec("cracking_pressure_Pa", type="float", default=0.0, label="Cracking pressure [Pa]"),
        ]

    def _add_field(self, spec: dict[str, Any]) -> None:
        key = spec["key"]
        widget: QWidget
        hint = get_schema_hint(self._payload, key)
        label_text = spec["label"]
        if hint and hint.required:
            label_text += " *"
        label = QLabel(label_text)
        if hint:
            label.setToolTip(hint.tooltip())
        if spec["type"] in {"choice", "enum"}:
            widget = QComboBox()
            widget.addItems([str(v) for v in spec.get("choices", [])])
            value = self._get_value(key)
            idx = widget.findText(str(value))
            if idx >= 0:
                widget.setCurrentIndex(idx)
            widget.currentTextChanged.connect(lambda txt, k=key: self._on_widget_changed(k, txt))
            if hint:
                widget.setToolTip(hint.tooltip())
        elif spec["type"] == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(self._get_value(key)))
            widget.toggled.connect(lambda state, k=key: self._on_widget_changed(k, bool(state)))
            if hint:
                widget.setToolTip(hint.tooltip())
        elif spec["type"] == "yaml":
            widget = ConfigTextEdit()
            widget.setMinimumHeight(110)
            widget.setPlainText(_format_yaml_value(self._get_value(key)))
            if hint:
                widget.setToolTip(hint.tooltip())
                if hint.default_text and not widget.toPlainText().strip():
                    widget.setPlaceholderText(hint.default_text)
            widget.editingFinished.connect(lambda k=key, w=widget, t=spec["type"]: self._on_text_finished(k, w, t))
        else:
            widget = QLineEdit(str(self._get_value(key) if self._get_value(key) is not None else ""))
            if hint:
                widget.setToolTip(hint.tooltip())
                if hint.default_text and not widget.text().strip():
                    widget.setPlaceholderText(hint.default_text)
            widget.editingFinished.connect(lambda k=key, w=widget, t=spec["type"]: self._on_line_finished(k, w, t))
        help_text = str(spec.get("help", "")).strip()
        if help_text:
            label.setToolTip(help_text)
            widget.setToolTip(help_text)
            container_tip = help_text
        else:
            container_tip = ""
        self._widgets[key] = widget
        container = QWidget()
        lay = QHBoxLayout(container)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(widget)
        if container_tip:
            container.setToolTip(container_tip)
        self._row_containers[key] = container
        self._row_labels[key] = label
        form = self._ensure_tab_form(str(spec.get("tab", "") or self._tab_name_for_key(key)))
        self._row_forms[key] = form
        form.addRow(label, container)

    def _get_value(self, dotted_key: str) -> Any:
        if self._data is None:
            return None
        parts = dotted_key.split(".")
        obj: Any = self._data
        for part in parts:
            if isinstance(obj, dict):
                obj = obj.get(part)
            else:
                return None
        return obj

    def _set_value(self, dotted_key: str, value: Any) -> None:
        if self._data is None:
            return
        parts = dotted_key.split(".")
        obj = self._data
        for part in parts[:-1]:
            if part not in obj or not isinstance(obj[part], dict):
                obj[part] = {}
            obj = obj[part]
        obj[parts[-1]] = value

    def _on_line_finished(self, key: str, widget: QLineEdit, kind: str) -> None:
        text = widget.text().strip()
        try:
            if kind == "float":
                value = None if text == "" else float(text.replace(",", "."))
                widget.setText("" if value is None else str(value))
            elif kind == "int":
                value = None if text == "" else int(float(text.replace(",", ".")))
                widget.setText("" if value is None else str(value))
            else:
                value = text
        except ValueError:
            old_value = self._get_value(key)
            widget.setText("" if old_value is None else str(old_value))
            hint = get_schema_hint(self._payload, key)
            extra = f"\n\n{hint.tooltip()}" if hint else ""
            show_warning(self, "Ungültiger Wert", f"Für '{key}' ist der eingegebene Wert ungültig.{extra}")
            return
        self._on_widget_changed(key, value)

    def _on_text_finished(self, key: str, widget: ConfigTextEdit, kind: str) -> None:
        text = widget.toPlainText().strip()
        try:
            if kind == "yaml":
                value = None if text == "" else yaml.safe_load(text)
                normalized = _format_yaml_value(value)
                if widget.toPlainText().strip() != normalized:
                    widget.blockSignals(True)
                    widget.setPlainText(normalized)
                    widget.blockSignals(False)
            else:
                value = text
        except Exception:
            old_value = self._get_value(key)
            widget.blockSignals(True)
            widget.setPlainText(_format_yaml_value(old_value))
            widget.blockSignals(False)
            hint = get_schema_hint(self._payload, key)
            extra = f"\n\n{hint.tooltip()}" if hint else ""
            show_warning(self, "Ungültiger Wert", f"Für '{key}' ist der eingegebene YAML-Wert ungültig.{extra}")
            return
        self._on_widget_changed(key, value)

    def _on_widget_changed(self, key: str, value: Any) -> None:
        if self._updating or self._data is None:
            return
        self._set_value(key, value)
        if key == "combustion.model" and value == "hcci_diesel":
            self._set_value("combustion.duration_mode", "time")
            if self._get_value("combustion.ignition.model") is None:
                legacy_model = self._get_value("combustion.ignition_model")
                self._set_value("combustion.ignition.model", legacy_model or "livengood_wu")
        if key == "combustion.model" and value == "vibe" and self._get_value("combustion.duration_mode") is None:
            self._set_value("combustion.duration_mode", "angle")
        self._apply_dynamic_visibility()
        self.value_changed.emit(key, value)

    def _apply_dynamic_visibility(self) -> None:
        for key, container in self._row_containers.items():
            visible = True
            spec = None
            payload = self._payload
            volume_names: list[str] = []
            if payload and self._data is not None:
                for s in self._field_specs(payload, self._data, volume_names):
                    if s["key"] == key:
                        spec = s
                        break
            if spec and "visible_if" in spec:
                visible = self._visible_if_matches(spec["visible_if"])
            container.setVisible(visible)
            label = self._row_labels.get(key)
            if label is not None:
                label.setVisible(visible)

    def _visible_if_matches(self, condition: Any) -> bool:
        if not condition:
            return True
        if isinstance(condition, tuple) and len(condition) == 2 and isinstance(condition[0], str):
            dep_key, dep_value = condition
            current = self._get_value(dep_key)
            if isinstance(dep_value, (list, tuple, set)):
                return current in dep_value
            return current == dep_value
        if isinstance(condition, list):
            return all(self._visible_if_matches(item) for item in condition)
        if isinstance(condition, dict):
            if "any" in condition:
                items = condition.get("any")
                return isinstance(items, list) and any(self._visible_if_matches(item) for item in items)
            if "all" in condition:
                items = condition.get("all")
                return isinstance(items, list) and all(self._visible_if_matches(item) for item in items)
        return True


class TopologyConfigEditor(QMainWindow):
    def __init__(self, config_path: str | Path | None = None):
        super().__init__()
        self.settings = QSettings("OpenAI", "Thermo0DTopologyConfigEditor")
        self.current_config_path: Path | None = None
        self.current_layout_path: Path | None = None
        self.state: dict[str, Any] = self._new_default_state()
        self.node_items: dict[str, DiagramNodeItem] = {}
        self.edge_visuals: list[EdgeVisual] = []
        self.connect_mode = False
        self.connect_steps: dict[str, str | None] = {"conn": None, "from": None, "to": None}
        self.last_selected_volume_id: str | None = None
        self.active_submodel_selection: tuple[str, str] | None = None

        self.setWindowTitle("Thermo0D Topology Config Editor")
        self.resize(1680, 980)
        self.setDockOptions(QMainWindow.DockOption.AllowNestedDocks | QMainWindow.DockOption.AllowTabbedDocks | QMainWindow.DockOption.GroupedDragging | QMainWindow.DockOption.AnimatedDocks)
        self._build_ui()
        self._build_actions()
        self._apply_saved_style()
        self._restore_settings()

        if config_path is None:
            last = self.settings.value("last_config_path", "", str)
            config_path = Path(last) if last else None
        if config_path:
            try:
                self.load_config(Path(config_path))
            except Exception as exc:
                show_warning(self, "Config laden", f"Letzte Datei konnte nicht geladen werden:\n{exc}")
                self._sync_all()
        else:
            self._sync_all()
        self._update_status_labels()

        self.showMaximized()
        self.status.showMessage("Bereit", 2500)

    def _apply_dark_palette(self) -> None:
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor("#0f172a"))
        pal.setColor(QPalette.ColorRole.WindowText, QColor("#e2e8f0"))
        pal.setColor(QPalette.ColorRole.Base, QColor("#111827"))
        pal.setColor(QPalette.ColorRole.AlternateBase, QColor("#1f2937"))
        pal.setColor(QPalette.ColorRole.Text, QColor("#e5e7eb"))
        pal.setColor(QPalette.ColorRole.Button, QColor("#111827"))
        pal.setColor(QPalette.ColorRole.ButtonText, QColor("#e5e7eb"))
        pal.setColor(QPalette.ColorRole.Highlight, QColor("#2563eb"))
        pal.setColor(QPalette.ColorRole.HighlightedText, QColor("white"))
        self.setPalette(pal)
        self.setStyleSheet(
            "QMainWindow{background:#0f172a;}"
            "QTreeWidget,QTextEdit,QLineEdit,QComboBox,QScrollArea{background:#111827;color:#e5e7eb;border:1px solid #334155;border-radius:6px;}"
            "QToolBar{spacing:6px;border-bottom:1px solid #334155;background:#0b1220;}"
            "QDockWidget::title{background:#111827;padding:6px;border-bottom:1px solid #334155;}"
            "QGroupBox{border:1px solid #334155;border-radius:8px;margin-top:8px;padding-top:8px;}"
            "QGroupBox::title{subcontrol-origin:margin;left:10px;padding:0 4px;}"
            "QPushButton{background:#1e293b;color:#e5e7eb;border:1px solid #334155;border-radius:6px;padding:6px 10px;}"
            "QPushButton:checked{background:#2563eb;}"
        )

    def _build_ui(self) -> None:
        self.status = QStatusBar()
        self.setStatusBar(self.status)
        self.status_config = QLabel()
        self.status_selection = QLabel()
        for label in (self.status_config, self.status_selection):
            label.setFrameStyle(QFrame.Panel | QFrame.Sunken)
            label.setContentsMargins(6, 0, 6, 0)
            self.status.addPermanentWidget(label)

        self.palette_tree = PaletteTree()
        self.palette_tree.add_requested.connect(self.create_item_at_view_center)
        left_dock = QDockWidget("Bauteil-Bibliothek")
        self.dock_palette = left_dock
        left_dock.setWidget(self.palette_tree)
        left_dock.setObjectName("dock_palette")
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, left_dock)

        self.node_list = NodeListPanel()
        self.node_list.selection_requested.connect(self.select_model_in_scene)
        self.node_list.add_requested.connect(self.create_item_at_view_center)
        node_dock = QDockWidget("Elemente")
        self.dock_nodes = node_dock
        node_dock.setWidget(self.node_list)
        node_dock.setObjectName("dock_nodes")
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, node_dock)
        self.tabifyDockWidget(self.dock_palette, self.dock_nodes)

        self.submodel_library = SubmodelLibraryPanel()
        self.submodel_library.selection_requested.connect(self.select_submodel)
        self.submodel_library.add_requested.connect(self.create_submodel)
        self.submodel_library.apply_requested.connect(self.apply_submodel_to_selection)
        self.submodel_library.delete_requested.connect(self.delete_submodel)
        submodel_dock = QDockWidget("Submodelle")
        self.dock_submodels = submodel_dock
        submodel_dock.setWidget(self.submodel_library)
        submodel_dock.setObjectName("dock_submodels")
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, submodel_dock)
        self.tabifyDockWidget(self.dock_nodes, self.dock_submodels)

        self.scene = TopologyScene(self)
        self.scene.selection_payload_changed.connect(self._on_scene_selection_changed)
        self.scene.changed.connect(lambda _: self._update_edges())
        self.view = TopologyGraphicsView(self.scene)
        self.setCentralWidget(self.view)

        self.properties = PropertyPanel()
        self.properties.value_changed.connect(self._on_property_value_changed)
        prop_dock = QDockWidget("Eigenschaften")
        self.dock_properties = prop_dock
        prop_dock.setWidget(self.properties)
        prop_dock.setObjectName("dock_properties")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, prop_dock)

        self.yaml_preview = QTextEdit()
        self.yaml_preview.setReadOnly(True)
        yaml_dock = QDockWidget("YAML Vorschau")
        self.dock_yaml = yaml_dock
        yaml_dock.setWidget(self.yaml_preview)
        yaml_dock.setObjectName("dock_yaml")
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, yaml_dock)

        self.problem_panel = ProblemPanel()
        self.problem_panel.selection_requested.connect(self.select_model_in_scene)
        problem_dock = QDockWidget("Pruefung")
        self.dock_problems = problem_dock
        problem_dock.setWidget(self.problem_panel)
        problem_dock.setObjectName("dock_problems")
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, problem_dock)
        self.tabifyDockWidget(self.dock_yaml, self.dock_problems)

    def _build_actions(self) -> None:
        menu_file = self.menuBar().addMenu("Datei")
        menu_view = self.menuBar().addMenu("Ansicht")
        menu_layout = self.menuBar().addMenu("Layout")
        menu_style = self.menuBar().addMenu("Style")

        tb = QToolBar("Hauptwerkzeuge")
        tb.setObjectName("toolbar_main")
        self.addToolBar(tb)

        self.act_new = QAction("Neu", self)
        self.act_new.triggered.connect(self.new_config)
        self.act_open = QAction("Laden", self)
        self.act_open.triggered.connect(self.open_dialog)
        self.act_save = QAction("Speichern", self)
        self.act_save.triggered.connect(self.save)
        self.act_save_as = QAction("Speichern unter", self)
        self.act_save_as.triggered.connect(self.save_as)
        self.act_delete = QAction("Löschen", self)
        self.act_delete.setShortcut("Delete")
        self.act_delete.triggered.connect(self.delete_selected)
        self.act_rename = QAction("Umbenennen", self)
        self.act_rename.setShortcut("F2")
        self.act_rename.triggered.connect(self.rename_selected_item)
        self.act_duplicate = QAction("Duplizieren", self)
        self.act_duplicate.setShortcut("Ctrl+D")
        self.act_duplicate.triggered.connect(self.duplicate_selected_item)
        self.act_zoom_in = QAction("Zoom +", self)
        self.act_zoom_in.setShortcut("Ctrl++")
        self.act_zoom_in.triggered.connect(self.view.zoom_in)
        self.act_zoom_out = QAction("Zoom -", self)
        self.act_zoom_out.setShortcut("Ctrl+-")
        self.act_zoom_out.triggered.connect(self.view.zoom_out)
        self.act_zoom_reset = QAction("100 %", self)
        self.act_zoom_reset.triggered.connect(self.view.reset_zoom)
        self.act_fit_view = QAction("Alles einpassen", self)
        self.act_fit_view.setShortcut("Ctrl+0")
        self.act_fit_view.triggered.connect(self.view.fit_all)
        self.act_center_selection = QAction("Auf Auswahl zentrieren", self)
        self.act_center_selection.triggered.connect(self.view.center_on_selection)
        self.act_auto_layout = QAction("Automatisch anordnen", self)
        self.act_auto_layout.setShortcut("Ctrl+L")
        self.act_auto_layout.triggered.connect(self.auto_arrange)
        self.act_cancel_connection = QAction("Verbindung abbrechen", self)
        self.act_cancel_connection.setShortcut("Esc")
        self.act_cancel_connection.triggered.connect(self.cancel_connection_assignment)
        self.act_project_settings = QAction("Projekt wählen", self)
        self.act_project_settings.triggered.connect(self.select_project_root)
        self.act_reset_layout = QAction("Layout zurücksetzen", self)
        self.act_reset_layout.triggered.connect(self.reset_layout)
        self.act_save_layout = QAction("Layout speichern", self)
        self.act_save_layout.triggered.connect(self.save_layout_state)

        for act in (self.act_new, self.act_open, self.act_save, self.act_save_as):
            menu_file.addAction(act)
            tb.addAction(act)
        menu_file.addSeparator()
        act_quit = QAction("Beenden", self)
        act_quit.triggered.connect(self.close)
        menu_file.addAction(act_quit)

        tb.addSeparator()
        for act in (self.act_delete, self.act_rename, self.act_duplicate):
            menu_file.addAction(act)
            tb.addAction(act)

        for dock in (self.dock_palette, self.dock_nodes, self.dock_submodels, self.dock_properties, self.dock_yaml, self.dock_problems):
            menu_view.addAction(dock.toggleViewAction())
        menu_view.addSeparator()
        for act in (self.act_zoom_in, self.act_zoom_out, self.act_zoom_reset, self.act_fit_view, self.act_center_selection, self.act_auto_layout, self.act_cancel_connection, self.act_project_settings):
            menu_view.addAction(act)

        menu_layout.addAction(self.act_save_layout)
        menu_layout.addAction(self.act_reset_layout)

        self.style_actions = []
        self.style_action_group = QActionGroup(self)
        self.style_action_group.setExclusive(True)
        for style_name in sorted(QStyleFactory.keys()):
            act = QAction(style_name, self)
            act.setCheckable(True)
            act.triggered.connect(lambda checked=False, n=style_name: self.apply_style(n))
            self.style_action_group.addAction(act)
            menu_style.addAction(act)
            self.style_actions.append(act)

        tb.addSeparator()
        for act in (self.act_fit_view, self.act_auto_layout, self.act_project_settings):
            tb.addAction(act)

        info = QLabel("Tipp: Drossel waehlen, dann Strg-Klick auf FROM- und TO-Volumen. Esc bricht ab.")
        info.setStyleSheet("color:#94a3b8;padding-left:8px;")
        tb.addWidget(info)
    def _apply_saved_style(self) -> None:
        style_name = self.settings.value("ui/style_name", QApplication.style().objectName(), str)
        available = {name.lower(): name for name in QStyleFactory.keys()}
        key = style_name.lower()
        if key not in available and available:
            style_name = sorted(available.values())[0]
        elif key in available:
            style_name = available[key]
        self.apply_style(style_name, announce=False)

    def _restore_settings(self) -> None:
        geo = self.settings.value("window/geometry")
        state = self.settings.value("window/state")
        restored = False
        if isinstance(geo, QByteArray):
            restored = bool(self.restoreGeometry(geo))
        if isinstance(state, QByteArray):
            restored = bool(self.restoreState(state)) or restored
        if not restored:
            self.reset_layout(announce=False)

    def closeEvent(self, event):
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        if self.current_config_path:
            self.settings.setValue("last_config_path", str(self.current_config_path))
            try:
                self._write_layout_file()
            except Exception as exc:
                self.status.showMessage(f"Layout konnte nicht gespeichert werden: {exc}", 5000)
        super().closeEvent(event)

    def save_layout_state(self) -> None:
        self.settings.setValue("window/geometry", self.saveGeometry())
        self.settings.setValue("window/state", self.saveState())
        self._write_layout_file()
        self.status.showMessage("Layout gespeichert", 2500)

    def _capture_layout_state(self) -> dict[str, Any]:
        nodes = self.state.setdefault("_layout", {}).setdefault("nodes", {})
        for model_id, node in self.node_items.items():
            nodes[model_id] = {
                "x": float(node.pos().x()),
                "y": float(node.pos().y()),
                "w": float(node.rect().width()),
                "h": float(node.rect().height()),
            }
        return {"nodes": nodes}

    def _write_layout_file(self) -> None:
        if not self.current_layout_path:
            return
        layout_payload = self._capture_layout_state()
        self.current_layout_path.write_text(json.dumps(layout_payload, indent=2), encoding="utf-8")

    def reset_layout(self, announce: bool = True) -> None:
        self.removeDockWidget(self.dock_palette)
        self.removeDockWidget(self.dock_nodes)
        self.removeDockWidget(self.dock_submodels)
        self.removeDockWidget(self.dock_properties)
        self.removeDockWidget(self.dock_yaml)
        self.removeDockWidget(self.dock_problems)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_palette)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_nodes)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.dock_submodels)
        self.tabifyDockWidget(self.dock_palette, self.dock_nodes)
        self.tabifyDockWidget(self.dock_nodes, self.dock_submodels)
        self.addDockWidget(Qt.RightDockWidgetArea, self.dock_properties)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_yaml)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.dock_problems)
        self.tabifyDockWidget(self.dock_yaml, self.dock_problems)
        self.resize(1680, 980)
        self.view.fit_all()
        if announce:
            self.status.showMessage("Layout zurückgesetzt", 2500)

    def apply_style(self, style_name: str, announce: bool = True) -> None:
        QApplication.setStyle(QStyleFactory.create(style_name))
        self.settings.setValue("ui/style_name", style_name)
        for act in getattr(self, "style_actions", []):
            act.blockSignals(True)
            act.setChecked(act.text() == style_name)
            act.blockSignals(False)
        if announce:
            self.status.showMessage(f"Style gewechselt: {style_name}", 2500)

    def _update_status_labels(self) -> None:
        config_text = str(self.current_config_path) if self.current_config_path else '—'
        selected = ''
        items = list(self.scene.selectedItems()) if hasattr(self, 'scene') else []
        if items:
            selected = ', '.join(getattr(item, 'model_id', '') for item in items if getattr(item, 'model_id', ''))
        self.status_config.setText(f'Config: {config_text}')
        self.status_selection.setText(f'Auswahl: {selected or "—"}')

    def rename_item_dialog(self, model_id: str) -> None:
        model = self._find_model(model_id)
        if model is None:
            return
        new_name, ok = get_text(self, "Objekt umbenennen", "Name:", text=model.get("name", ""))
        if ok and new_name.strip():
            self._rename_model(model_id, new_name.strip())

    def rename_selected_item(self) -> None:
        selected = self.scene.selectedItems()
        if selected and isinstance(selected[0], DiagramNodeItem):
            self.rename_item_dialog(selected[0].model_id)

    def duplicate_selected_item(self) -> None:
        selected = self.scene.selectedItems()
        if selected and isinstance(selected[0], DiagramNodeItem):
            self._duplicate_model(selected[0].model_id)

    def cancel_connection_assignment(self) -> None:
        if not self.connect_steps.get("conn"):
            return
        self.connect_steps = {"conn": None, "from": None, "to": None}
        self.status.showMessage("Verbindung abgebrochen.", 2500)

    def auto_arrange(self) -> None:
        volumes = self.state["preprocessing"]["volumes"]
        connections = self.state["preprocessing"]["connections"]
        for index, model in enumerate(volumes):
            node = self.node_items.get(model.get("name", ""))
            if node is not None:
                node.setPos(QPointF(-320.0, -160.0 + index * 120.0))
        for index, model in enumerate(connections):
            node = self.node_items.get(model.get("name", ""))
            if node is not None:
                node.setPos(QPointF(120.0, -160.0 + index * 105.0))
        self._sync_all()
        self.view.fit_all()
        self.status.showMessage("Topologie automatisch angeordnet.", 2500)

    def _topology_problems(self) -> list[dict[str, str]]:
        problems: list[dict[str, str]] = []
        volumes = self.state["preprocessing"]["volumes"]
        connections = self.state["preprocessing"]["connections"]
        names: dict[str, int] = {}
        for model in [*volumes, *connections]:
            name = str(model.get("name", "")).strip()
            if not name:
                problems.append({"severity": "Fehler", "model_id": "", "text": "Ein Element hat keinen Namen."})
                continue
            names[name] = names.get(name, 0) + 1
        for name, count in names.items():
            if count > 1:
                problems.append({"severity": "Fehler", "model_id": name, "text": f"Name mehrfach vergeben: {name}"})
        volume_names = {str(v.get("name", "")) for v in volumes}
        if not volumes:
            problems.append({"severity": "Hinweis", "model_id": "", "text": "Noch keine Volumen angelegt."})
        for conn in connections:
            conn_id = str(conn.get("name", ""))
            src = str(conn.get("from_volume", "") or "")
            dst = str(conn.get("to_volume", "") or "")
            if not src:
                problems.append({"severity": "Fehler", "model_id": conn_id, "text": f"{conn_id}: FROM-Volumen fehlt."})
            elif src not in volume_names:
                problems.append({"severity": "Fehler", "model_id": conn_id, "text": f"{conn_id}: FROM-Volumen existiert nicht: {src}"})
            if not dst:
                problems.append({"severity": "Fehler", "model_id": conn_id, "text": f"{conn_id}: TO-Volumen fehlt."})
            elif dst not in volume_names:
                problems.append({"severity": "Fehler", "model_id": conn_id, "text": f"{conn_id}: TO-Volumen existiert nicht: {dst}"})
            if src and dst and src == dst:
                problems.append({"severity": "Hinweis", "model_id": conn_id, "text": f"{conn_id}: FROM und TO sind identisch."})
        connected = {str(c.get("from_volume", "") or "") for c in connections} | {str(c.get("to_volume", "") or "") for c in connections}
        for vol in volumes:
            name = str(vol.get("name", ""))
            if name and name not in connected:
                problems.append({"severity": "Hinweis", "model_id": name, "text": f"{name}: noch nicht verbunden."})
            for submodel_type in SUBMODEL_LIBRARY_TYPES:
                sub = vol.get(submodel_type)
                if not isinstance(sub, dict):
                    continue
                ref = str(sub.get("ref", "") or "")
                if ref and ref not in self._submodels_state().get(submodel_type, {}):
                    label = SUBMODEL_LABELS.get(submodel_type, submodel_type)
                    problems.append({"severity": "Fehler", "model_id": name, "text": f"{name}: {label}-ref existiert nicht: {ref}"})
            combustion = vol.get("combustion")
            if isinstance(combustion, dict):
                diag_ref = str(combustion.get("hcci_diagnostics_ref", "") or "")
                if diag_ref:
                    submodels = self._submodels_state()
                    if diag_ref not in submodels.get("ignition", {}) and diag_ref not in submodels.get("combustion", {}):
                        problems.append({"severity": "Fehler", "model_id": name, "text": f"{name}: HCCI-Diagnose-ref existiert nicht: {diag_ref}"})
        return problems

    def _rename_model(self, old: str, new: str) -> None:
        model = self._find_model(old)
        if model is None or not new or old == new:
            return
        if self._find_model(new) is not None:
            show_warning(self, "Umbenennen", f"Ein Objekt mit dem Namen '{new}' existiert bereits.")
            return
        model["name"] = new
        node = self.node_items.pop(old, None)
        if node is not None:
            node.model_id = new
            self.node_items[new] = node
        layout = self.state.setdefault("_layout", {}).setdefault("nodes", {})
        if old in layout:
            layout[new] = layout.pop(old)
        for conn in self.state["preprocessing"]["connections"]:
            if conn.get("from_volume") == old:
                conn["from_volume"] = new
            if conn.get("to_volume") == old:
                conn["to_volume"] = new
        self._sync_all(select_id=new)
    def _duplicate_model(self, model_id: str) -> None:
        model = self._find_model(model_id)
        node = self.node_items.get(model_id)
        if model is None or node is None:
            return
        clone = _deepcopy_jsonable(model)
        base_name = f"{model_id}_copy"
        new_name = base_name
        idx = 2
        while self._find_model(new_name) is not None:
            new_name = f"{base_name}_{idx}"
            idx += 1
        clone["name"] = new_name
        if clone.get("type") in VOLUME_TYPES:
            self.state["preprocessing"]["volumes"].append(clone)
        else:
            self.state["preprocessing"]["connections"].append(clone)
        offset_pos = node.pos() + QPointF(42.0, 36.0)
        layout = self.state.setdefault("_layout", {}).setdefault("nodes", {})
        layout[new_name] = {
            "x": float(offset_pos.x()),
            "y": float(offset_pos.y()),
            "w": float(node.rect().width()),
            "h": float(node.rect().height()),
        }
        self._create_scene_node(clone, offset_pos, layout[new_name])
        self._sync_all(select_id=new_name)
        self.status.showMessage(f"Duplikat erstellt: {new_name}", 3000)

    def _start_connection_assignment(self, conn_id: str) -> None:
        conn = self._find_model(conn_id)
        if conn is None or conn.get("type") not in CONNECTION_TYPES:
            return
        self.connect_steps = {"conn": conn_id, "from": None, "to": None}
        self.status.showMessage(f"Verbindung setzen: FROM-Volumen für {conn_id} wählen.", 5000)

    def _assign_connection_endpoint_from_volume(self, volume_id: str) -> bool:
        if self.connect_steps["conn"] is None:
            return False
        model = self._find_model(volume_id)
        if model is None or model.get("type") not in VOLUME_TYPES:
            return False
        if self.connect_steps["from"] is None:
            self.connect_steps["from"] = volume_id
            self.status.showMessage(f"FROM gesetzt: {volume_id} | Jetzt TO-Volumen wählen.", 5000)
            return True
        if self.connect_steps["to"] is None and volume_id != self.connect_steps["from"]:
            self.connect_steps["to"] = volume_id
            conn_id = str(self.connect_steps["conn"])
            conn = self._find_model(conn_id)
            if conn is not None:
                conn["from_volume"] = str(self.connect_steps["from"])
                conn["to_volume"] = str(self.connect_steps["to"])
            self.connect_steps = {"conn": None, "from": None, "to": None}
            self._sync_all(select_id=conn_id)
            self.status.showMessage(f"Verbindung gesetzt: {conn_id}", 4000)
            return True
        return False

    def show_item_context_menu(self, node: DiagramNodeItem, screen_pos) -> None:
        if node is None:
            return
        model = self._find_model(node.model_id)
        if model is None:
            return
        self.scene.clearSelection()
        node.setSelected(True)
        self._on_scene_selection_changed({"kind": "node", "id": node.model_id, "type": node.item_type})

        menu = QMenu(self)
        act_rename = menu.addAction("Umbenennen")
        act_duplicate = menu.addAction("Duplizieren")
        act_delete = menu.addAction("Löschen")
        menu.addSeparator()
        act_center = menu.addAction("Auf Auswahl zentrieren")
        menu.addSeparator()

        connection_action = None
        if model.get("type") in CONNECTION_TYPES:
            connection_action = menu.addAction("Verbindung setzen")
        elif model.get("type") in VOLUME_TYPES and self.connect_steps.get("conn"):
            pending = str(self.connect_steps.get("conn"))
            label = "Verbindung setzen (als FROM)" if self.connect_steps.get("from") is None else "Verbindung setzen (als TO)"
            connection_action = menu.addAction(f"{label}: {pending}")

        chosen = menu.exec(screen_pos)
        if chosen is None:
            return
        if chosen == act_rename:
            self.rename_item_dialog(node.model_id)
            return
        if chosen == act_duplicate:
            self._duplicate_model(node.model_id)
            return
        if chosen == act_delete:
            self.delete_selected()
            return
        if chosen == act_center:
            self.view.centerOn(node)
            self.status.showMessage(f"Auf {node.model_id} zentriert.", 2500)
            return
        if connection_action is not None and chosen == connection_action:
            if model.get("type") in CONNECTION_TYPES:
                self._start_connection_assignment(node.model_id)
            else:
                self._assign_connection_endpoint_from_volume(node.model_id)
            return

    def select_project_root(self) -> None:
        self.scene.clearSelection()
        self.active_submodel_selection = None
        self.properties.set_payload("Projekt", {"kind": "root"}, self.state, self._volume_names(), self._submodel_ref_choices())
        self.status.showMessage("Projekteigenschaften aktiv.", 2500)

    def create_item_at_view_center(self, item_type: str) -> None:
        center = self.view.mapToScene(self.view.viewport().rect().center())
        self.create_item_from_palette(item_type, center)

    def select_model_in_scene(self, model_id: str) -> None:
        node = self.node_items.get(model_id)
        if node is None:
            return
        self.scene.clearSelection()
        node.setSelected(True)
        self.view.centerOn(node)
        self._on_scene_selection_changed({"kind": "node", "id": model_id, "type": node.item_type})

    def handle_ctrl_link_click(self, model_id: str) -> None:
        model = self._find_model(model_id)
        if model is None:
            return
        if model["type"] in CONNECTION_TYPES:
            self._start_connection_assignment(model_id)
            self.status.showMessage(f"Strg-Verknüpfung: FROM-Volumen für {model['name']} wählen.")
            return
        if model["type"] in VOLUME_TYPES and self.connect_steps["conn"] is not None:
            if self._assign_connection_endpoint_from_volume(model_id):
                return

    def on_node_resized(self, model_id: str, width: float, height: float) -> None:
        self.state.setdefault("_layout", {}).setdefault("nodes", {}).setdefault(model_id, {})["w"] = float(width)
        self.state.setdefault("_layout", {}).setdefault("nodes", {}).setdefault(model_id, {})["h"] = float(height)
        self._update_edges()

    def _new_default_state(self) -> dict[str, Any]:
        return {
            "versioning": current_versioning_dict(),
            "test_description": "",
            "preprocessing": {
                "gas_properties": {"cp_J_per_kgK": 1005.0, "cv_J_per_kgK": 718.0, "R_J_per_kgK": 287.0, "thermo_model": "constant"},
                "features": {"mass_flow": True, "wall_heat": False, "combustion": False, "evaporation": False, "pv_work": True},
                "engine": {"cycle_type": "4t", "speed_rpm": 3000.0},
                "submodels": {key: {} for key in SUBMODEL_LIBRARY_TYPES},
                "volumes": [],
                "connections": [],
            },
            "simulation": {
                "dt_s": 2.0e-5,
                "total_cycles": 3,
                "save_last_cycles": 1,
                "simulationtime": None,
                "solver": {"kind": "rk4", "rtol": 1.0e-6, "atol": 1.0e-9},
            },
            "postprocessing": {
                "csv_enabled": True,
                "mode": "pipeline",
                "config": None,
                "csv_path": "results/editor_export.csv",
                "csv_separator": ";",
                "excel_enabled": False,
                "excel_path": "results/editor_export.xlsx",
                "sampling": {"mode": "crank_angle", "step_deg": 5.0},
                "final_cycle_uniform_angle_export": {"enabled": False, "step_deg": 1.0},
                "free_piston_last_ut_ot_ut_export": {"enabled": False, "step_deg": 1.0, "axis_min_deg": 0.0, "axis_max_deg": 360.0},
                "check_report": {"enabled": True, "html_enabled": False},
                "plots": {
                    "enabled": True,
                    "source": "last_cycle_uniform",
                    "output_dir": "results/plots",
                    "layouts": {"auto_create_defaults": True, "entries": []},
                },
                "console": {
                    "run_summary": {"enabled": True},
                    "cycle_summary": {"enabled": True},
                    "check_report": {"enabled": True},
                    "geometry": {"enabled": True},
                },
            },
            "_layout": {"nodes": {}},
        }

    def new_config(self) -> None:
        self.current_config_path = None
        self.current_layout_path = None
        self.state = self._new_default_state()
        self._clear_scene()
        self._sync_all()
        self._update_status_labels()
        self.view.fit_all()
        self.status.showMessage("Neue Konfiguration erstellt.", 3000)

    def open_dialog(self) -> None:
        path, _ = get_open_file_name(self, "Konfiguration laden", str(Path.cwd()), "YAML (*.yaml *.yml)")
        if path:
            self.load_config(Path(path))

    def load_config(self, path: Path) -> None:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if isinstance(raw, dict) and requires_version_upgrade(raw):
            loaded_schema = config_schema_version_from_document(raw)
            answer = ask_question(
                self,
                "Alte Konfigurationsversion",
                build_upgrade_message(path, loaded_schema),
                buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                default_button=QMessageBox.StandardButton.Yes,
            )
            if answer == QMessageBox.StandardButton.Yes:
                try:
                    raw = migrate_config_file_in_place(path, raw)
                    self.status.showMessage(
                        f"Konfigurationsversion aktualisiert: Schema {loaded_schema} → {CURRENT_CONFIG_SCHEMA_VERSION}",
                        5000,
                    )
                except Exception as exc:
                    show_critical(self, "Versionsupdate fehlgeschlagen", str(exc))
                    return
        self.current_config_path = path.resolve()
        self.current_layout_path = path.with_suffix(path.suffix + ".layout.json")
        self.state = raw
        self.state.setdefault("test_description", "")
        self.state.setdefault("preprocessing", {})
        self.state["preprocessing"].setdefault("gas_properties", {"cp_J_per_kgK": 1005.0, "cv_J_per_kgK": 718.0, "R_J_per_kgK": 287.0, "thermo_model": "constant"})
        self.state["preprocessing"].setdefault("features", {"mass_flow": True, "wall_heat": False, "combustion": False, "evaporation": False, "pv_work": True})
        self.state["preprocessing"].setdefault("engine", {"cycle_type": "4t", "speed_rpm": 3000.0})
        self._submodels_state()
        self.state["preprocessing"].setdefault("volumes", [])
        self.state["preprocessing"].setdefault("connections", [])
        _fill_ref_types_for_editor_inplace(self.state)
        self.state.setdefault("simulation", self._new_default_state()["simulation"])
        self.state.setdefault("postprocessing", self._new_default_state()["postprocessing"])
        _merge_defaults_inplace(self.state["simulation"], self._new_default_state()["simulation"])
        _merge_defaults_inplace(self.state["postprocessing"], self._new_default_state()["postprocessing"])
        self.state.setdefault("_layout", {"nodes": {}})
        self._clear_scene()
        self._populate_scene_from_state()
        self._sync_all()
        self._update_status_labels()
        self.view.fit_all()
        self.status.showMessage(f"Geladen: {path}", 4000)

    def save(self) -> None:
        if self.current_config_path is None:
            self.save_as()
            return
        self._write_config(self.current_config_path)

    def save_as(self) -> None:
        path, _ = get_save_file_name(self, "Konfiguration speichern", str(Path.cwd() / "config.yaml"), "YAML (*.yaml *.yml)")
        if not path:
            return
        self.current_config_path = Path(path).resolve()
        self.current_layout_path = self.current_config_path.with_suffix(self.current_config_path.suffix + ".layout.json")
        self._write_config(self.current_config_path)

    def _write_config(self, path: Path) -> None:
        payload = self._export_state_without_layout()
        path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True), encoding="utf-8")
        self._write_layout_file()
        self.settings.setValue("last_config_path", str(path))
        self.status.showMessage(f"Gespeichert: {path.name}", 4000)

    def _export_state_without_layout(self) -> dict[str, Any]:
        state = _deepcopy_jsonable(self.state)
        state.pop("_layout", None)
        _sanitize_disabled_submodels_inplace(state)
        _sanitize_mode_dependent_fields_inplace(state)
        _normalize_initial_states_inplace(state)
        for vol in state.get("preprocessing", {}).get("volumes", []):
            if isinstance(vol, dict) and vol.get("initial_pressure_Pa") is not None:
                vol.pop("initial_mass_kg", None)
        state = stamp_current_versioning(state)
        # Umgebungen und Drosseln sind reguläre, simulierbare Topologieobjekte.
        return state

    def _clear_scene(self) -> None:
        self.scene.clear()
        self.node_items.clear()
        self.edge_visuals.clear()

    def _populate_scene_from_state(self) -> None:
        layout_nodes = {}
        if self.current_layout_path and self.current_layout_path.exists():
            try:
                layout_nodes = json.loads(self.current_layout_path.read_text(encoding="utf-8")).get("nodes", {})
            except Exception:
                layout_nodes = {}
        else:
            layout_nodes = self.state.get("_layout", {}).get("nodes", {})
        x_vol = -260.0
        x_conn = 140.0
        yv = -120.0
        yc = -120.0
        for vol in self.state["preprocessing"]["volumes"]:
            pos = layout_nodes.get(vol["name"], {"x": x_vol, "y": yv})
            self._create_scene_node(vol, QPointF(float(pos.get("x", x_vol)), float(pos.get("y", yv))), pos)
            yv += 130.0
        for conn in self.state["preprocessing"]["connections"]:
            pos = layout_nodes.get(conn["name"], {"x": x_conn, "y": yc})
            self._create_scene_node(conn, QPointF(float(pos.get("x", x_conn)), float(pos.get("y", yc))), pos)
            yc += 130.0
        self._rebuild_all_edges()

    def create_item_from_palette(self, item_type: str, pos: QPointF) -> None:
        if item_type == "cylinder":
            model = {
                "name": _new_id("cyl"),
                "type": "cylinder",
                "initial_pressure_Pa": 1.0e6,
                "initial_temperature_K": 300.0,
                "kinematics": {"type": "crank_slider", "bore_m": 0.08, "stroke_m": 0.08, "conrod_m": 0.13, "compression_ratio": 10.0, "phase_deg": 0.0},
                "wall_heat": {"model": "none"},
                "wall_temperature": {"model": "none"},
                "combustion": {"model": "none"},
                "evaporation": {"model": "none"},
            }
            self.state["preprocessing"]["volumes"].append(model)
        elif item_type == "plenum":
            model = {
                "name": _new_id("plenum"),
                "type": "plenum",
                "initial_pressure_Pa": 1.0e5,
                "initial_temperature_K": 300.0,
                "fixed_volume_m3": 0.002,
                "wall_heat": {"model": "none"},
                "wall_temperature": {"model": "none"},
                "combustion": {"model": "none"},
                "evaporation": {"model": "none"},
            }
            self.state["preprocessing"]["volumes"].append(model)
        elif item_type == "bounce_chamber":
            model = {
                "name": _new_id("bounce"),
                "type": "bounce_chamber",
                "model": "gas_spring",
                "initial_pressure_Pa": 1.5e5,
                "initial_temperature_K": 300.0,
                "initial_burned_fraction_0to1": 0.0,
                "chamber_diameter_m": 0.07,
                "chamber_length_m": 0.08,
                "compression_ratio": 2.5,
                "p0_Pa": None,
                "polytropic_exponent": 1.3,
            }
            self.state["preprocessing"]["volumes"].append(model)
        elif item_type == "environment":
            model = {
                "name": _new_id("env"),
                "type": "environment",
                "pressure_Pa": 101325.0,
                "temperature_K": 298.15,
            }
            self.state["preprocessing"]["volumes"].append(model)
        elif item_type == "valve":
            model = {
                "name": _new_id("valve"),
                "type": "valve",
                "from_volume": "",
                "to_volume": "",
                "opening_angle_deg": 0.0,
                "opening_reference": "gas_exchange_tdc",
                "profile_angle_domain": "crank",
                "lift_scale": 1.0,
                "lash_m": 0.0,
                "lift_file": "data/intake_valve_lift.csv",
                "alpha_k_file": "data/intake_alpha_k.csv",
            }
            self.state["preprocessing"]["connections"].append(model)
        elif item_type == "slot":
            model = {
                "name": _new_id("slot"),
                "type": "slot",
                "from_volume": "",
                "to_volume": "",
                "source_of_data": "rectangle",
                "opening_mode": "by_distance",
                "distance_from_tdc_m": 0.01,
                "opening_angle_deg": None,
                "piston_height_if_crankcase_m": 0.0,
                "entrance_angle_deg": 0.0,
                "width_m": 0.01,
                "height_m": 0.02,
                "open_fillet_radius_m": 0.0,
                "full_fillet_radius_m": 0.0,
                "number_of_identical_holes": 1,
                "discharge_coefficients": {"mode": "constant", "forward_cd": 0.7, "reverse_cd": 0.7},
            }
            self.state["preprocessing"]["connections"].append(model)
        elif item_type == "orifice":
            model = {
                "name": _new_id("orifice"),
                "type": "orifice",
                "from_volume": "",
                "to_volume": "",
                "area_m2": 1.0e-4,
                "diameter_mm": None,
                "forward_cd": 0.7,
                "reverse_cd": 0.7,
            }
            self.state["preprocessing"]["connections"].append(model)
        elif item_type == "check_valve":
            model = {
                "name": _new_id("check"),
                "type": "check_valve",
                "from_volume": "",
                "to_volume": "",
                "area_m2": None,
                "diameter_mm": 10.0,
                "discharge_coefficient": 0.7,
                "cracking_pressure_Pa": 0.0,
            }
            self.state["preprocessing"]["connections"].append(model)
        else:
            return
        self._create_scene_node(model, pos)
        self._sync_all(select_id=model["name"])

    def _create_scene_node(self, model: dict[str, Any], pos: QPointF, layout_meta: dict[str, Any] | None = None) -> None:
        node = DiagramNodeItem(model["name"], model["type"], model["name"], self._subtitle_for_model(model), self)
        if layout_meta:
            default_w, default_h = DiagramNodeItem.default_size_for_type(str(model.get("type") or ""))
            w = float(layout_meta.get("w", default_w))
            h = float(layout_meta.get("h", default_h))
            if str(model.get("type") or "") in CONNECTION_TYPES and abs(w - NODE_SIZE[0]) < 1.0 and abs(h - NODE_SIZE[1]) < 1.0:
                w, h = default_w, default_h
            node.setRect(0.0, 0.0, w, h)
            node._layout_text()
        node.setPos(pos)
        self.scene.addItem(node)
        self.node_items[model["name"]] = node
        self.state.setdefault("_layout", {}).setdefault("nodes", {})[model["name"]] = {
            "x": float(pos.x()),
            "y": float(pos.y()),
            "w": float(node.rect().width()),
            "h": float(node.rect().height()),
        }

    def _subtitle_for_model(self, model: dict[str, Any]) -> str:
        t = model.get("type", "")
        if t in VOLUME_TYPES:
            return t.upper()
        if t in CONNECTION_TYPES:
            src = model.get("from_volume", "?") or "?"
            dst = model.get("to_volume", "?") or "?"
            return f"{t.upper()}  {src} → {dst}"
        return t

    def _find_model(self, model_id: str) -> dict[str, Any] | None:
        for group in (self.state["preprocessing"]["volumes"], self.state["preprocessing"]["connections"]):
            for model in group:
                if model["name"] == model_id:
                    return model
        return None

    def _volume_names(self) -> list[str]:
        return [v["name"] for v in self.state["preprocessing"]["volumes"]]

    def _submodel_ref_choices(self) -> dict[str, list[str]]:
        submodels = self._submodels_state()
        result: dict[str, list[str]] = {}
        for submodel_type in SUBMODEL_LIBRARY_TYPES:
            group = submodels.get(submodel_type, {})
            result[submodel_type] = sorted(str(name) for name in group) if isinstance(group, dict) else []
        return result

    def _submodels_state(self) -> dict[str, Any]:
        preprocessing = self.state.setdefault("preprocessing", {})
        submodels = preprocessing.setdefault("submodels", {})
        if not isinstance(submodels, dict):
            submodels = {}
            preprocessing["submodels"] = submodels
        for submodel_type in SUBMODEL_LIBRARY_TYPES:
            group = submodels.setdefault(submodel_type, {})
            if not isinstance(group, dict):
                submodels[submodel_type] = {}
        return submodels

    def _unique_submodel_name(self, submodel_type: str) -> str:
        prefix = {
            "wall_heat": "wall_heat",
            "wall_temperature": "wall_temperature",
            "combustion": "combustion",
            "evaporation": "evaporation",
        }.get(submodel_type, "submodel")
        group = self._submodels_state().setdefault(submodel_type, {})
        idx = 1
        while f"{prefix}_{idx}" in group:
            idx += 1
        return f"{prefix}_{idx}"

    def _default_submodel_payload(self, submodel_type: str) -> dict[str, Any]:
        if submodel_type == "wall_heat":
            return {
                "model": "woschni",
                "variant": "legacy",
                "wall_temperature_K": 450.0,
                "wall_area_m2": 0.02,
                "multiplier": 1.0,
                "dp_mode": "off",
                "reference_state_mode": "none",
                "phase_mode": "legacy",
                "c1": 2.28,
                "c2": 0.00324,
                "c3": 0.0,
            }
        if submodel_type == "wall_temperature":
            return {
                "model": "cycle_average",
                "relaxation": 0.3,
                "cylinder": {"initial_temperature_K": 430.0, "coolant_temperature_K": 360.0, "lambda_W_per_mK": 45.0, "wall_thickness_m": 0.006, "area_m2": 0.018},
                "head": {"initial_temperature_K": 470.0, "coolant_temperature_K": 370.0, "lambda_W_per_mK": 160.0, "wall_thickness_m": 0.010, "area_m2": 0.008},
                "piston": {"initial_temperature_K": 500.0, "coolant_temperature_K": 390.0, "lambda_W_per_mK": 160.0, "wall_thickness_m": 0.012, "area_m2": 0.006},
            }
        if submodel_type == "combustion":
            return {
                "model": "vibe",
                "start_mode": "angle",
                "start_deg": 350.0,
                "duration_mode": "angle",
                "duration_deg": 40.0,
                "a": 6.9,
                "m": 2.0,
                "fueling_mode": "fixed_energy",
                "added_energy_per_cycle_J": 400.0,
                "angle_reference": "absolute",
            }
        if submodel_type == "ignition":
            return {
                "model": "beck_2003_1_arrhenius",
                "beck_c1_s": 1.0e-5,
                "beck_c2": -1.2,
                "beck_reference_pressure_bar": 1.0,
                "beck_reference_o2_percent": 20.94,
                "tau_activation_temperature_K": 15000.0,
                "tau_reference_pressure_Pa": 1000000.0,
                "tau_reference_lambda": 1.4,
                "lambda_slowdown_exponent": 0.7,
                "residual_slowdown_factor": 1.5,
                "start_temperature_min_K": 780.0,
                "start_pressure_min_Pa": 2000000.0,
                "max_ignition_delay_s": 0.02,
                "accumulation_start_mode": "compression",
                "accumulation_end_mode": "none",
            }
        if submodel_type == "evaporation":
            return {
                "model": "simple",
                "start_deg": 300.0,
                "duration_deg": 30.0,
                "evaporated_mass_per_cycle_kg": 1.0e-5,
                "latent_heat_J_per_kg": 2.5e5,
                "angle_reference": "absolute",
            }
        return {"model": "none"}

    def create_submodel(self, submodel_type: str) -> None:
        if submodel_type not in SUBMODEL_LIBRARY_TYPES:
            return
        default_name = self._unique_submodel_name(submodel_type)
        name, ok = get_text(self, f"{SUBMODEL_LABELS[submodel_type]} anlegen", "Name:", text=default_name)
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        group = self._submodels_state().setdefault(submodel_type, {})
        if name in group:
            show_warning(self, "Submodell anlegen", f"Ein Submodell mit dem Namen '{name}' existiert bereits.")
            return
        group[name] = self._default_submodel_payload(submodel_type)
        self.select_submodel(submodel_type, name)
        self._sync_all(selected_submodel=(submodel_type, name))
        self.status.showMessage(f"Submodell angelegt: {name}", 3000)

    def select_submodel(self, submodel_type: str, name: str) -> None:
        group = self._submodels_state().get(submodel_type, {})
        if not isinstance(group, dict):
            return
        data = group.get(name)
        if not isinstance(data, dict):
            return
        self.scene.clearSelection()
        self.active_submodel_selection = (submodel_type, name)
        title = f"{SUBMODEL_LABELS.get(submodel_type, submodel_type)}: {name}"
        self.properties.set_payload(title, {"kind": "submodel", "type": submodel_type}, data, self._volume_names(), self._submodel_ref_choices())
        self.submodel_library.refresh(self._submodels_state(), (submodel_type, name))
        self.status.showMessage(f"Submodell ausgewaehlt: {name}", 2500)
        self._update_status_labels()

    def _target_volume_for_submodel_apply(self) -> dict[str, Any] | None:
        selected = self.scene.selectedItems()
        if selected and isinstance(selected[0], DiagramNodeItem):
            model = self._find_model(selected[0].model_id)
            if model is not None and model.get("type") in {"cylinder", "plenum"}:
                self.last_selected_volume_id = str(model.get("name", ""))
                return model
        if self.last_selected_volume_id:
            model = self._find_model(self.last_selected_volume_id)
            if model is not None and model.get("type") in {"cylinder", "plenum"}:
                return model
        return None

    def apply_submodel_to_selection(self, submodel_type: str, name: str) -> None:
        group = self._submodels_state().get(submodel_type, {})
        if not isinstance(group, dict) or name not in group:
            return
        target = self._target_volume_for_submodel_apply()
        if target is None:
            show_warning(self, "Submodell anwenden", "Bitte zuerst einen Zylinder oder ein Plenum auswaehlen.")
            return
        if submodel_type == "ignition":
            combustion = target.get("combustion")
            if not isinstance(combustion, dict) or combustion.get("model") != "vibe":
                show_warning(self, "Ignition-Diagnose anwenden", "Bitte ein Volumen mit combustion.model = vibe auswaehlen.")
                return
            combustion["hcci_diagnostics_ref"] = name
            self.state.setdefault("preprocessing", {}).setdefault("features", {})["combustion"] = True
            self._sync_all(select_id=str(target.get("name", "")), selected_submodel=(submodel_type, name))
            self.status.showMessage(f"Ignition-Diagnose {name} auf {target.get('name')} angewendet.", 3500)
            return
        target[submodel_type] = {"ref": name}
        feature_key = {"wall_heat": "wall_heat", "combustion": "combustion", "evaporation": "evaporation"}.get(submodel_type)
        if feature_key:
            self.state.setdefault("preprocessing", {}).setdefault("features", {})[feature_key] = True
        self._sync_all(select_id=str(target.get("name", "")), selected_submodel=(submodel_type, name))
        self.status.showMessage(f"{name} auf {target.get('name')} angewendet.", 3500)

    def delete_submodel(self, submodel_type: str, name: str) -> None:
        group = self._submodels_state().get(submodel_type, {})
        if not isinstance(group, dict) or name not in group:
            return
        answer = ask_question(
            self,
            "Submodell loeschen",
            f"Submodell '{name}' loeschen? Bestehende refs in Volumen bleiben sichtbar und werden in der Pruefung markiert.",
            buttons=QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            default_button=QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        group.pop(name, None)
        self._sync_all()
        self.status.showMessage(f"Submodell geloescht: {name}", 3000)

    def _on_scene_selection_changed(self, payload: dict[str, Any] | None) -> None:
        if payload is None:
            self.active_submodel_selection = None
            self.node_list.refresh(self.state["preprocessing"]["volumes"], self.state["preprocessing"]["connections"], None)
            self.properties.set_payload("Eigenschaften", {"kind": "root"}, self.state, self._volume_names(), self._submodel_ref_choices())
            return
        model = self._find_model(payload["id"])
        if model is None:
            self.active_submodel_selection = None
            self.properties.set_payload("Eigenschaften", {"kind": "root"}, self.state, self._volume_names(), self._submodel_ref_choices())
            return
        self.active_submodel_selection = None
        if model.get("type") in {"cylinder", "plenum"}:
            self.last_selected_volume_id = str(model.get("name", ""))
        self.node_list.refresh(self.state["preprocessing"]["volumes"], self.state["preprocessing"]["connections"], model["name"])
        self.properties.set_payload(model["name"], {"kind": "node", "type": model["type"]}, model, self._volume_names(), self._submodel_ref_choices())
        self.status.showMessage(f"Auswahl: {model['name']} ({model['type']})", 2000)
        self._update_status_labels()

    def _on_property_value_changed(self, key: str, value: Any) -> None:
        selected = self.scene.selectedItems()
        if not selected:
            self._sync_all(selected_submodel=self.active_submodel_selection)
            return
        item = selected[0]
        if not isinstance(item, DiagramNodeItem):
            self._sync_all()
            return
        model = self._find_model(item.model_id)
        if model is None:
            self._sync_all()
            return
        if key == "name":
            self._rename_model(item.model_id, str(value))
            return
        for submodel_type in SUBMODEL_LIBRARY_TYPES:
            if key == f"{submodel_type}.ref":
                if value:
                    model[submodel_type] = {"ref": str(value)}
                else:
                    model[submodel_type] = {"model": "none"}
                feature_key = {"wall_heat": "wall_heat", "combustion": "combustion", "evaporation": "evaporation"}.get(submodel_type)
                if feature_key and value:
                    self.state.setdefault("preprocessing", {}).setdefault("features", {})[feature_key] = True
                break
        item.set_labels(model["name"], self._subtitle_for_model(model))
        self._sync_all(select_id=item.model_id)

    def _sync_all(self, select_id: str | None = None, selected_submodel: tuple[str, str] | None = None) -> None:
        for model_id, node in self.node_items.items():
            model = self._find_model(model_id)
            if model is None:
                continue
            node.set_labels(model["name"], self._subtitle_for_model(model))
            self.state.setdefault("_layout", {}).setdefault("nodes", {})[model["name"]] = {"x": float(node.pos().x()), "y": float(node.pos().y()), "w": float(node.rect().width()), "h": float(node.rect().height())}
        self._rebuild_all_edges()
        self.yaml_preview.setPlainText(yaml.safe_dump(self._export_state_without_layout(), sort_keys=False, allow_unicode=True))
        active_id = select_id
        if select_id and select_id in self.node_items:
            self.scene.clearSelection()
            self.node_items[select_id].setSelected(True)
        elif self.scene.selectedItems() and isinstance(self.scene.selectedItems()[0], DiagramNodeItem):
            active_id = self.scene.selectedItems()[0].model_id
        elif not self.scene.selectedItems() and selected_submodel is None:
            self.properties.set_payload("Projekt", {"kind": "root"}, self.state, self._volume_names(), self._submodel_ref_choices())
        self.node_list.refresh(self.state["preprocessing"]["volumes"], self.state["preprocessing"]["connections"], active_id)
        if hasattr(self, "submodel_library"):
            self.submodel_library.refresh(self._submodels_state(), selected_submodel)
        if hasattr(self, "problem_panel"):
            self.problem_panel.refresh(self._topology_problems())
        self.status.showMessage(
            f"Volumen: {len(self.state['preprocessing']['volumes'])} | Verbindungen: {len(self.state['preprocessing']['connections'])}",
            1500,
        )
        self._update_status_labels()

    def _update_edges(self) -> None:
        for model_id, node in self.node_items.items():
            self.state.setdefault("_layout", {}).setdefault("nodes", {})[model_id] = {"x": float(node.pos().x()), "y": float(node.pos().y()), "w": float(node.rect().width()), "h": float(node.rect().height())}
        self._rebuild_all_edges()

    def _rebuild_all_edges(self) -> None:
        for ev in self.edge_visuals:
            self.scene.removeItem(ev.path_item)
            self.scene.removeItem(ev.label_item)
        self.edge_visuals.clear()
        for conn in self.state["preprocessing"]["connections"]:
            src = self.node_items.get(conn.get("from_volume", ""))
            mid = self.node_items.get(conn["name"])
            dst = self.node_items.get(conn.get("to_volume", ""))
            if mid is None:
                continue
            if src is not None:
                self.edge_visuals.append(self._create_edge(conn["name"], "from", src, mid, QColor("#38bdf8")))
            if dst is not None:
                self.edge_visuals.append(self._create_edge(conn["name"], "to", mid, dst, QColor("#f87171")))

    def _create_edge(self, conn_id: str, role: str, a: DiagramNodeItem, b: DiagramNodeItem, color: QColor) -> EdgeVisual:
        p0 = a.connection_anchor("from")
        p1 = b.connection_anchor("to")
        path = QPainterPath(p0)
        dx = (p1.x() - p0.x()) * 0.5
        path.cubicTo(p0 + QPointF(dx, 0.0), p1 - QPointF(dx, 0.0), p1)
        path_item = QGraphicsPathItem(path)
        pen = QPen(color, 2.0, Qt.PenStyle.DashLine)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        path_item.setPen(pen)
        path_item.setZValue(-2)
        label_item = QGraphicsTextItem("FROM" if role == "from" else "TO")
        label_item.setDefaultTextColor(color)
        label_item.setFont(QFont("Segoe UI", 8, weight=QFont.Weight.Bold))
        midpt = path.pointAtPercent(0.5)
        label_item.setPos(midpt + QPointF(6.0, -14.0))
        label_item.setZValue(-1)
        self.scene.addItem(path_item)
        self.scene.addItem(label_item)
        return EdgeVisual(conn_id, role, path_item, label_item)

    def delete_selected(self) -> None:
        selected = self.scene.selectedItems()
        if not selected:
            return
        item = selected[0]
        if not isinstance(item, DiagramNodeItem):
            return
        model = self._find_model(item.model_id)
        if model is None:
            return
        if model["type"] in VOLUME_TYPES:
            self.state["preprocessing"]["volumes"] = [v for v in self.state["preprocessing"]["volumes"] if v["name"] != item.model_id]
            for conn in self.state["preprocessing"]["connections"]:
                if conn.get("from_volume") == item.model_id:
                    conn["from_volume"] = ""
                if conn.get("to_volume") == item.model_id:
                    conn["to_volume"] = ""
        else:
            self.state["preprocessing"]["connections"] = [c for c in self.state["preprocessing"]["connections"] if c["name"] != item.model_id]
        self.node_items.pop(item.model_id, None)
        self.state.setdefault("_layout", {}).setdefault("nodes", {}).pop(item.model_id, None)
        self.scene.removeItem(item)
        self._sync_all()
        self._update_status_labels()


def launch(config_path: str | Path | None = None) -> int:
    app = QApplication.instance()
    owns_app = app is None
    if app is None:
        app = QApplication(sys.argv)
    app.setOrganizationName("OpenAI")
    app.setApplicationName("Thermo0DTopologyConfigEditor")
    window = TopologyConfigEditor(config_path)
    show_foreground(window)
    if owns_app:
        return int(app.exec())
    return 0


__all__ = ["TopologyConfigEditor", "launch"]
