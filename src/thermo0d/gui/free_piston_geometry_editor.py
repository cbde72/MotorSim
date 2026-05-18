from __future__ import annotations

import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

try:
    import yaml
except Exception:  # pragma: no cover
    yaml = None

from PySide6.QtCore import QPointF, QRectF, QSettings, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QPainter, QPen, QBrush
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDockWidget,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QToolBar,
    QStyleFactory,
    QStatusBar,
    QVBoxLayout,
    QWidget,
)

from thermo0d.gui.dialogs import show_foreground

APP_TITLE = "Free-Piston Geometry Editor"
APP_ORG = "OpenAI"
APP_NAME = "Thermo0DFreePistonGeometryEditor"


@dataclass
class SlotGeometry:
    name: str
    distance_from_tdc_m: float
    height_m: float
    width_m: float
    count: int

    def open_height_m(self, distance_from_tdc_m: float) -> float:
        return max(0.0, min(self.height_m, distance_from_tdc_m - self.distance_from_tdc_m))

    def area_geom_m2(self, distance_from_tdc_m: float) -> float:
        return self.count * self.width_m * self.open_height_m(distance_from_tdc_m)

    def opens_at_m(self) -> float:
        return self.distance_from_tdc_m

    def fully_open_at_m(self) -> float:
        return self.distance_from_tdc_m + self.height_m

    def closes_below_m(self) -> float:
        return self.distance_from_tdc_m


@dataclass
class FreePistonGeometry:
    x_min_m: float = -0.04
    x_max_m: float = 0.04
    piston_diameter_m: float = 0.0745
    compression_ratio: float = 10.0
    bounce_diameter_m: float = 0.0745
    bounce_length_m: float = 0.08
    bounce_compression_ratio: float = 2.5
    transfer: SlotGeometry | None = None
    exhaust: SlotGeometry | None = None

    @property
    def stroke_m(self) -> float:
        return self.x_max_m - self.x_min_m

    @property
    def piston_area_m2(self) -> float:
        return 0.25 * math.pi * self.piston_diameter_m * self.piston_diameter_m

    @property
    def clearance_volume_m3(self) -> float:
        return self.swept_volume_m3 / max(self.compression_ratio - 1.0, 1.0e-12)

    @property
    def swept_volume_m3(self) -> float:
        return self.piston_area_m2 * self.stroke_m

    @property
    def bounce_chamber_cross_section_m2(self) -> float:
        return 0.25 * math.pi * self.bounce_diameter_m * self.bounce_diameter_m

    @property
    def bounce_swept_volume_m3(self) -> float:
        return self.bounce_chamber_cross_section_m2 * self.bounce_length_m

    @property
    def bounce_area_m2(self) -> float:
        return self.bounce_swept_volume_m3 / max(self.stroke_m, 1.0e-12)

    @property
    def bounce_volume_min_m3(self) -> float:
        return self.bounce_swept_volume_m3 / max(self.bounce_compression_ratio - 1.0, 1.0e-12)

    @property
    def bounce_volume0_m3(self) -> float:
        return self.bounce_swept_volume_m3 + self.bounce_volume_min_m3

    def bounce_volume_m3(self, x_m: float) -> float:
        distance_from_ut_m = self.x_max_m - x_m
        return self.bounce_volume0_m3 - self.bounce_area_m2 * (x_m - self.x_min_m)

    def distance_from_tdc_m(self, x_m: float) -> float:
        return self.x_max_m - x_m

    def x_from_distance_m(self, distance_m: float) -> float:
        return self.x_max_m - distance_m

    def volume_m3(self, x_m: float) -> float:
        return self.clearance_volume_m3 + self.piston_area_m2 * self.distance_from_tdc_m(x_m)


class SectionPreview(QGraphicsView):
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QColor("#0b1220"))
        self.setScene(QGraphicsScene(self))
        self.geometry_model = FreePistonGeometry()
        self.current_x_m = 0.0
        self.show_distance_labels = True
        self.refresh()

    def set_model(self, model: FreePistonGeometry, x_m: float) -> None:
        self.geometry_model = model
        self.current_x_m = x_m
        self.refresh()

    def refresh(self) -> None:
        scene = self.scene()
        assert scene is not None
        scene.clear()

        model = self.geometry_model
        x_m = self.current_x_m
        dist_m = model.distance_from_tdc_m(x_m)

        W, H = 940, 760
        scene.setSceneRect(0, 0, W, H)

        margin_top = 70
        cyl_h = 560
        bore_w = 160
        cx = W / 2
        left = cx - bore_w / 2
        right = cx + bore_w / 2
        px_per_mm = cyl_h / max(1.0, model.stroke_m * 1000.0)
        tdc_y = margin_top
        bdc_y = margin_top + cyl_h
        piston_y = tdc_y + dist_m * 1000.0 * px_per_mm
        piston_h = 42

        def add_text(x: float, y: float, text: str, color: str = "#e5edf8", size: int = 12):
            item = QGraphicsSimpleTextItem(text)
            item.setBrush(QBrush(QColor(color)))
            font = item.font()
            font.setPointSize(size)
            item.setFont(font)
            item.setPos(x, y)
            scene.addItem(item)
            return item

        scene.addRect(QRectF(left - 24, tdc_y - 20, bore_w + 48, cyl_h + 80), QPen(QColor("#22314b"), 2), QBrush(QColor("#101a2e")))
        scene.addRect(QRectF(left, tdc_y, bore_w, cyl_h), QPen(QColor("#cbd5e1"), 3), QBrush(QColor("#132238")))
        scene.addRect(QRectF(left + 10, tdc_y + 10, bore_w - 20, cyl_h - 20), QPen(QColor("#334155"), 1), QBrush(Qt.NoBrush))
        scene.addRect(QRectF(left - 8, tdc_y - 26, bore_w + 16, 26), QPen(QColor("#dbeafe"), 2), QBrush(QColor("#7c8aa6")))

        # Grid and labels
        total_mm = int(round(model.stroke_m * 1000.0))
        for mm in range(0, total_mm + 1, 5):
            y = tdc_y + mm * px_per_mm
            pen = QPen(QColor("#233251" if mm % 10 == 0 else "#1b2943"), 1)
            scene.addLine(120, y, 820, y, pen)
            add_text(70, y - 8, f"{mm}", "#94a3b8", 10 if mm % 10 else 11)

        add_text(140, 18, "Free-Piston TDC/BDC Diagnose", "#e5edf8", 18)
        add_text(140, 42, "Section preview mit Config -> Geometrie -> Physik", "#94a3b8", 11)

        # TDC/BDC markers
        scene.addLine(right + 10, tdc_y, right + 72, tdc_y, QPen(QColor("#dbeafe"), 2))
        add_text(right + 80, tdc_y - 10, f"TDC = x_max = {model.x_max_m*1000:.1f} mm", "#dbeafe", 12)
        scene.addLine(right + 10, bdc_y, right + 72, bdc_y, QPen(QColor("#fca5a5"), 2))
        add_text(right + 80, bdc_y - 10, f"BDC = x_min = {model.x_min_m*1000:.1f} mm", "#fca5a5", 12)

        # Slots
        def draw_slot(slot: SlotGeometry | None, side: str, color: str) -> None:
            if slot is None:
                return
            slot_top_y = tdc_y + slot.distance_from_tdc_m * 1000.0 * px_per_mm
            slot_h = slot.height_m * 1000.0 * px_per_mm
            open_h = slot.open_height_m(dist_m)
            open_h_px = open_h * 1000.0 * px_per_mm
            open_y = slot_top_y + slot_h - open_h_px
            if side == "left":
                slot_x = left - 72
                outer_x = left - 110
            else:
                slot_x = right
                outer_x = right + 84
            scene.addRect(QRectF(slot_x, slot_top_y, 72, slot_h), QPen(QColor(color), 2), QBrush(QColor("#0f172a")))
            scene.addRect(QRectF(slot_x, open_y, 72, open_h_px), QPen(Qt.NoPen), QBrush(QColor("#34d399")))
            scene.addRect(QRectF(outer_x, slot_top_y + 4, 24, max(0.0, slot_h - 8)), QPen(QColor(color), 2), QBrush(QColor("#0f172a")))
            scene.addRect(QRectF(outer_x, open_y + 4, 24, max(0.0, open_h_px - 8)), QPen(Qt.NoPen), QBrush(QColor("#34d399")))
            label_x = slot_x - 120 if side == "left" else slot_x + 86
            add_text(label_x, slot_top_y - 14, slot.name, color, 12)
            add_text(label_x, slot_top_y + slot_h + 4, f"open @ {slot.opens_at_m()*1000:.1f} mm", "#94a3b8", 10)
            add_text(label_x, slot_top_y + slot_h + 20, f"full @ {slot.fully_open_at_m()*1000:.1f} mm", "#94a3b8", 10)

        draw_slot(model.transfer, "left", "#38bdf8")
        draw_slot(model.exhaust, "right", "#f87171")

        # Piston and measurement
        scene.addRect(QRectF(left + 10, piston_y, bore_w - 20, piston_h), QPen(QColor("#d7e1ef"), 2), QBrush(QColor("#8b9bb4")))
        scene.addLine(left - 10, piston_y, right + 10, piston_y, QPen(QColor("#fbbf24"), 2, Qt.DashLine))
        add_text(right + 80, piston_y - 10, f"Kolbenoberkante x = {x_m*1000:.1f} mm", "#fbbf24", 12)

        scene.addLine(cx, tdc_y, cx, piston_y, QPen(QColor("#34d399"), 3))
        add_text(cx + 12, (tdc_y + piston_y) / 2 - 10, f"distance_from_tdc = x_max - x = {dist_m*1000:.1f} mm", "#34d399", 12)

        # Footer formulas
        footer = QGraphicsRectItem(QRectF(90, 650, 760, 90))
        footer.setPen(QPen(QColor("#22314b"), 1.5))
        footer.setBrush(QBrush(QColor(255, 255, 255, 10)))
        scene.addItem(footer)
        add_text(110, 668, f"Hub = x_max - x_min = {model.x_max_m*1000:.1f} - ({model.x_min_m*1000:.1f}) = {model.stroke_m*1000:.1f} mm", "#e5edf8", 12)
        add_text(110, 690, f"V_cyl = Vc + A_piston * distance_from_tdc = {model.clearance_volume_m3:.6g} + {model.piston_area_m2:.6g} * {dist_m:.6f}", "#cbd5e1", 11)
        add_text(110, 712, f"V_cyl = {model.volume_m3(x_m)*1e6:.2f} cm³", "#cbd5e1", 11)


class SignalPlotView(QGraphicsView):
    def __init__(self, title: str, parent: Optional[QWidget] = None):
        super().__init__(parent)
        self.title = title
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setBackgroundBrush(QColor("#0b1220"))
        self.setScene(QGraphicsScene(self))
        self.setMinimumHeight(220)

    def plot_curve(self, xs_mm: list[float], ys: list[float], y_label: str, current_x_mm: float | None = None, current_y: float | None = None, color: str = "#38bdf8") -> None:
        scene = self.scene()
        assert scene is not None
        scene.clear()
        W, H = 560, 220
        scene.setSceneRect(0, 0, W, H)
        m = 36
        scene.addRect(QRectF(0, 0, W, H), QPen(QColor("#22314b"), 1), QBrush(QColor("#101a2e")))
        x0, y0, x1, y1 = m, H - m, W - m, m
        scene.addLine(x0, y0, x1, y0, QPen(QColor("#334155"), 1))
        scene.addLine(x0, y0, x0, y1, QPen(QColor("#334155"), 1))
        item = QGraphicsSimpleTextItem(self.title)
        item.setBrush(QBrush(QColor("#e5edf8")))
        item.setPos(10, 6)
        scene.addItem(item)
        yl = QGraphicsSimpleTextItem(y_label)
        yl.setBrush(QBrush(QColor("#94a3b8")))
        yl.setPos(10, 24)
        scene.addItem(yl)
        if not xs_mm or not ys:
            return
        xmin, xmax = min(xs_mm), max(xs_mm)
        ymin, ymax = min(ys), max(ys)
        if math.isclose(xmin, xmax):
            xmax = xmin + 1.0
        if math.isclose(ymin, ymax):
            ymax = ymin + 1.0
        path_points = []
        for x, y in zip(xs_mm, ys):
            px = x0 + (x - xmin) / (xmax - xmin) * (x1 - x0)
            py = y0 - (y - ymin) / (ymax - ymin) * (y0 - y1)
            path_points.append(QPointF(px, py))
        for i in range(1, len(path_points)):
            scene.addLine(QGraphicsLineItem(path_points[i-1].x(), path_points[i-1].y(), path_points[i].x(), path_points[i].y()).line(), QPen(QColor(color), 2))
        if current_x_mm is not None and current_y is not None:
            px = x0 + (current_x_mm - xmin) / (xmax - xmin) * (x1 - x0)
            py = y0 - (current_y - ymin) / (ymax - ymin) * (y0 - y1)
            scene.addLine(px, y0, px, y1, QPen(QColor("#fbbf24"), 1, Qt.DashLine))
            scene.addEllipse(QRectF(px - 4, py - 4, 8, 8), QPen(QColor("#fbbf24")), QBrush(QColor("#fbbf24")))


class FreePistonGeometryEditor(QMainWindow):
    def __init__(self, config_path: Optional[str] = None) -> None:
        super().__init__()
        self.settings = QSettings(APP_ORG, APP_NAME)
        self.setWindowTitle(APP_TITLE)
        self.resize(1600, 980)
        self.current_config_path: Optional[Path] = None
        self.model = FreePistonGeometry(
            transfer=SlotGeometry("Transfer", 0.055, 0.012, 0.020, 2),
            exhaust=SlotGeometry("Auslass", 0.045, 0.014, 0.024, 2),
        )
        self.current_x_m = 0.0
        self.style_action_group = QActionGroup(self)
        self.style_action_group.setExclusive(True)

        self._build_window()
        self._build_actions()
        self._build_menu()
        self._build_toolbar()
        self._build_statusbar()
        self._build_docks()
        self._populate_style_menu()
        self._apply_saved_style()
        self._restore_layout()

        initial_path = Path(config_path).expanduser() if config_path else self._last_config_path()
        if initial_path is not None and initial_path.exists():
            self.load_config(initial_path)
        else:
            self.refresh_all()
        self.showMaximized()
        self.statusBar().showMessage("Bereit", 2500)

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
        self.act_open = QAction("Config laden…", self)
        self.act_open.triggered.connect(self.on_open_config)
        self.act_save_report = QAction("Diagnosebericht speichern…", self)
        self.act_save_report.triggered.connect(self.on_save_report)
        self.act_refresh = QAction("Refresh", self)
        self.act_refresh.triggered.connect(self.refresh_all)
        self.act_layout_save = QAction("Layout speichern", self)
        self.act_layout_save.triggered.connect(self.save_layout_to_settings)
        self.act_layout_reset = QAction("Layout zurücksetzen", self)
        self.act_layout_reset.triggered.connect(self.reset_layout)
        self.act_quit = QAction("Beenden", self)
        self.act_quit.triggered.connect(self.close)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("Datei")
        file_menu.addAction(self.act_open)
        file_menu.addAction(self.act_save_report)
        file_menu.addSeparator()
        file_menu.addAction(self.act_quit)

        self.view_menu = self.menuBar().addMenu("Ansicht")
        self.layout_menu = self.menuBar().addMenu("Layout")
        self.layout_menu.addAction(self.act_layout_save)
        self.layout_menu.addAction(self.act_layout_reset)
        self.style_menu = self.menuBar().addMenu("Style")

    def _build_toolbar(self) -> None:
        tb = QToolBar("Hauptwerkzeuge", self)
        tb.setMovable(False)
        self.addToolBar(tb)
        for action in [self.act_open, self.act_save_report, self.act_refresh]:
            tb.addAction(action)
        tb.addSeparator()
        tb.addAction(self.act_layout_save)
        tb.addAction(self.act_layout_reset)

    def _build_statusbar(self) -> None:
        status = QStatusBar(self)
        self.setStatusBar(status)
        self.status_config = QLabel()
        self.status_position = QLabel()
        self.status_metrics = QLabel()
        for label in [self.status_config, self.status_position, self.status_metrics]:
            label.setFrameStyle(QFrame.Panel | QFrame.Sunken)
            label.setContentsMargins(6, 0, 6, 0)
            status.addPermanentWidget(label)

    def _build_docks(self) -> None:
        self.controls_panel = self._build_controls_panel()
        self.preview_panel = self._build_preview_panel()
        self.formula_text = QTextEdit()
        self.formula_text.setReadOnly(True)

        self.controls_dock = self._create_dock("Geometry", self._make_scroll(self.controls_panel))
        self.preview_dock = self._create_dock("Preview", self.preview_panel)
        self.report_dock = self._create_dock("Diagnose", self.formula_text)
        self.all_docks = [self.controls_dock, self.preview_dock, self.report_dock]
        self._apply_default_layout()
        for dock in self.all_docks:
            self.view_menu.addAction(dock.toggleViewAction())

    def _build_controls_panel(self) -> QWidget:
        root = QWidget()
        left_layout = QVBoxLayout(root)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.setSpacing(8)

        cfg_group = QGroupBox("Konfiguration / Physikbezug")
        cfg_form = QFormLayout(cfg_group)

        self.x_min = self._mk_spin(-500, 500, 1, -40)
        self.x_max = self._mk_spin(-500, 500, 1, 40)
        self.piston_diameter = self._mk_spin(1, 500, 0.1, 74.5)
        self.compression_ratio = self._mk_spin(1.01, 200.0, 0.1, 10.0)
        self.bounce_diameter = self._mk_spin(1, 1000, 0.1, 74.5)
        self.bounce_length = self._mk_spin(0.1, 2000, 0.1, 80.0)
        self.bounce_compression_ratio = self._mk_spin(1.01, 100.0, 0.01, 2.5)
        self.current_x = self._mk_spin(-500, 500, 0.1, 0.0)
        self.current_x.valueChanged.connect(self.on_x_changed)

        cfg_form.addRow("x_min [mm]", self.x_min)
        cfg_form.addRow("x_max [mm]", self.x_max)
        cfg_form.addRow("Kolbendurchmesser [mm]", self.piston_diameter)
        cfg_form.addRow("Verdichtungsverhältnis [-]", self.compression_ratio)
        cfg_form.addRow("Bounce-Durchmesser [mm]", self.bounce_diameter)
        cfg_form.addRow("Bounce-Hublänge [mm]", self.bounce_length)
        cfg_form.addRow("Bounce-Verdichtungsverhältnis [-]", self.bounce_compression_ratio)
        cfg_form.addRow("aktuelles x [mm]", self.current_x)
        left_layout.addWidget(cfg_group)

        slot_group = QGroupBox("Slots aus Config / Geometrie")
        slots = QFormLayout(slot_group)
        self.tr_dist = self._mk_spin(0, 500, 0.1, 55)
        self.tr_h = self._mk_spin(0, 200, 0.1, 12)
        self.tr_w = self._mk_spin(0, 500, 0.1, 20)
        self.tr_n = self._mk_spin(1, 20, 1, 2, decimals=0)
        self.ex_dist = self._mk_spin(0, 500, 0.1, 45)
        self.ex_h = self._mk_spin(0, 200, 0.1, 14)
        self.ex_w = self._mk_spin(0, 500, 0.1, 24)
        self.ex_n = self._mk_spin(1, 20, 1, 2, decimals=0)
        for w in [self.tr_dist, self.tr_h, self.tr_w, self.tr_n, self.ex_dist, self.ex_h, self.ex_w, self.ex_n]:
            w.valueChanged.connect(self.refresh_all)
        slots.addRow(QLabel("Transfer"))
        slots.addRow("distance_from_tdc [mm]", self.tr_dist)
        slots.addRow("height [mm]", self.tr_h)
        slots.addRow("width [mm]", self.tr_w)
        slots.addRow("count", self.tr_n)
        slots.addRow(QLabel("Auslass"))
        slots.addRow("distance_from_tdc [mm]", self.ex_dist)
        slots.addRow("height [mm]", self.ex_h)
        slots.addRow("width [mm]", self.ex_w)
        slots.addRow("count", self.ex_n)
        left_layout.addWidget(slot_group)

        btn_row = QHBoxLayout()
        apply_btn = QPushButton("Geometrie anwenden")
        apply_btn.clicked.connect(self.refresh_all)
        center_tdc_btn = QPushButton("auf TDC")
        center_tdc_btn.clicked.connect(lambda: self.current_x.setValue(self.x_max.value()))
        center_bdc_btn = QPushButton("auf BDC")
        center_bdc_btn.clicked.connect(lambda: self.current_x.setValue(self.x_min.value()))
        center_mid_btn = QPushButton("Mitte")
        center_mid_btn.clicked.connect(lambda: self.current_x.setValue((self.x_min.value() + self.x_max.value()) / 2.0))
        btn_row.addWidget(apply_btn)
        btn_row.addWidget(center_tdc_btn)
        btn_row.addWidget(center_bdc_btn)
        btn_row.addWidget(center_mid_btn)
        left_layout.addLayout(btn_row)

        self.summary_table = QTableWidget(0, 4)
        self.summary_table.setHorizontalHeaderLabels(["Thema", "Config", "Modell", "Bewertung"])
        self.summary_table.horizontalHeader().setStretchLastSection(True)
        self.summary_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        left_layout.addWidget(self.summary_table, 1)

        for w in [self.x_min, self.x_max, self.piston_diameter, self.compression_ratio, self.bounce_diameter, self.bounce_length, self.bounce_compression_ratio]:
            w.valueChanged.connect(self.refresh_all)
        return root

    def _build_preview_panel(self) -> QWidget:
        root = QWidget()
        right_layout = QVBoxLayout(root)
        right_layout.setContentsMargins(8, 8, 8, 8)
        right_layout.setSpacing(8)
        self.preview = SectionPreview()
        right_layout.addWidget(self.preview, 3)
        plots_row = QHBoxLayout()
        self.plot_slot = SignalPlotView("Slotöffnung über Abstand von TDC")
        self.plot_vol = SignalPlotView("Zylindervolumen über Abstand von TDC")
        plots_row.addWidget(self.plot_slot, 1)
        plots_row.addWidget(self.plot_vol, 1)
        right_layout.addLayout(plots_row, 2)
        return root

    def _create_dock(self, title: str, widget: QWidget) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(f"dock_{title.lower().replace(' ', '_')}")
        dock.setWidget(widget)
        dock.setAllowedAreas(Qt.AllDockWidgetAreas)
        dock.setFeatures(QDockWidget.DockWidgetClosable | QDockWidget.DockWidgetMovable | QDockWidget.DockWidgetFloatable)
        dock.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        return dock

    def _make_scroll(self, widget: QWidget) -> QWidget:
        wrapper = QWidget()
        layout = QVBoxLayout(wrapper)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(widget)
        return wrapper

    def _apply_default_layout(self) -> None:
        for dock in getattr(self, 'all_docks', []):
            self.removeDockWidget(dock)
        self.addDockWidget(Qt.LeftDockWidgetArea, self.controls_dock)
        self.addDockWidget(Qt.RightDockWidgetArea, self.preview_dock)
        self.addDockWidget(Qt.BottomDockWidgetArea, self.report_dock)

    def _restore_layout(self) -> None:
        geometry = self.settings.value('window/geometry')
        state = self.settings.value('window/state')
        restored = False
        if geometry:
            restored = bool(self.restoreGeometry(geometry))
        if state:
            restored = bool(self.restoreState(state)) or restored
        if not restored:
            self._apply_default_layout()

    def save_layout_to_settings(self) -> None:
        self.settings.setValue('window/geometry', self.saveGeometry())
        self.settings.setValue('window/state', self.saveState())
        self.settings.sync()
        self.statusBar().showMessage('Layout gespeichert', 2500)

    def reset_layout(self) -> None:
        self.settings.remove('window/geometry')
        self.settings.remove('window/state')
        self._apply_default_layout()
        self.statusBar().showMessage('Layout zurückgesetzt', 2500)

    def _populate_style_menu(self) -> None:
        self.style_menu.clear()
        for style_name in sorted(QStyleFactory.keys()):
            action = QAction(style_name, self)
            action.setCheckable(True)
            action.triggered.connect(lambda checked=False, name=style_name: self.apply_style(name))
            self.style_action_group.addAction(action)
            self.style_menu.addAction(action)

    def _apply_saved_style(self) -> None:
        style_name = str(self.settings.value('ui/style_name', QApplication.style().objectName()))
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
            self.settings.setValue('ui/style_name', style_name)
            for action in self.style_action_group.actions():
                action.blockSignals(True)
                action.setChecked(action.text() == style_name)
                action.blockSignals(False)
            self._update_statusbar_fields()
            if announce:
                self.statusBar().showMessage(f'Style gewechselt: {style_name}', 2500)

    def _last_config_path(self) -> Optional[Path]:
        text = str(self.settings.value('files/last_config_path', '') or '').strip()
        if not text:
            return None
        candidate = Path(text).expanduser()
        return candidate if candidate.exists() else None

    def _update_statusbar_fields(self) -> None:
        model = self.model
        config_text = str(self.current_config_path) if self.current_config_path else '—'
        self.status_config.setText(f'Config: {config_text}')
        self.status_position.setText(f'x={self.current_x_m * 1000.0:.2f} mm | Hub={model.stroke_m * 1000.0:.2f} mm')
        self.status_metrics.setText(f'Vs={model.swept_volume_m3 * 1e6:.2f} cm³ | CR={model.compression_ratio:.3f}')

    def closeEvent(self, event) -> None:
        self.save_layout_to_settings()
        if self.current_config_path is not None:
            self.settings.setValue('files/last_config_path', str(self.current_config_path))
        super().closeEvent(event)

    def _mk_spin(self, mn: float, mx: float, step: float, value: float, decimals: int = 3) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(mn, mx)
        s.setDecimals(decimals)
        s.setSingleStep(step)
        s.setValue(value)
        return s

    def on_x_changed(self, value: float) -> None:
        self.current_x_m = value / 1000.0
        self.refresh_all()

    def collect_model(self) -> FreePistonGeometry:
        model = FreePistonGeometry(
            x_min_m=self.x_min.value() / 1000.0,
            x_max_m=self.x_max.value() / 1000.0,
            piston_diameter_m=self.piston_diameter.value() / 1000.0,
            compression_ratio=self.compression_ratio.value(),
            bounce_diameter_m=self.bounce_diameter.value() / 1000.0,
            bounce_length_m=self.bounce_length.value() / 1000.0,
            bounce_compression_ratio=self.bounce_compression_ratio.value(),
            transfer=SlotGeometry(
                "Transfer",
                self.tr_dist.value() / 1000.0,
                self.tr_h.value() / 1000.0,
                self.tr_w.value() / 1000.0,
                int(round(self.tr_n.value())),
            ),
            exhaust=SlotGeometry(
                "Auslass",
                self.ex_dist.value() / 1000.0,
                self.ex_h.value() / 1000.0,
                self.ex_w.value() / 1000.0,
                int(round(self.ex_n.value())),
            ),
        )
        self.model = model
        self.current_x_m = self.current_x.value() / 1000.0
        return model

    def refresh_all(self) -> None:
        model = self.collect_model()
        if model.x_max_m <= model.x_min_m:
            return
        self.preview.set_model(model, self.current_x_m)
        self.refresh_summary()
        self.refresh_plots()
        self.refresh_formula_text()
        self._update_statusbar_fields()

    def refresh_summary(self) -> None:
        model = self.model
        x_m = self.current_x_m
        dist = model.distance_from_tdc_m(x_m)
        rows = [
            ("TDC", f"x_max = {model.x_max_m*1000:.1f} mm", f"TDC = {model.x_max_m*1000:.1f} mm", "ok"),
            ("BDC", f"x_min = {model.x_min_m*1000:.1f} mm", f"BDC = {model.x_min_m*1000:.1f} mm", "ok"),
            ("Hub", f"x_max - x_min", f"{model.stroke_m*1000:.1f} mm", "ok" if math.isclose(model.stroke_m*1000.0, 80.0, rel_tol=0, abs_tol=0.2) else "prüfen"),
            ("Position", f"x = {x_m*1000:.1f} mm", f"distance_from_tdc = {dist*1000:.1f} mm", "ok"),
            ("Zylinder", f"D={model.piston_diameter_m*1000:.2f} mm, CR={model.compression_ratio:.3f}", f"A={model.piston_area_m2*1e6:.1f} mm², Vc={model.clearance_volume_m3*1e6:.2f} cm³", "ok"),
            ("Bounce", f"D={model.bounce_diameter_m*1000:.2f} mm, Lh={model.bounce_length_m*1000:.2f} mm, CR={model.bounce_compression_ratio:.3f}", f"Vh={model.bounce_swept_volume_m3*1e6:.2f} cm³, Vmax@OT={model.bounce_volume0_m3*1e6:.2f} cm³, V={model.bounce_volume_m3(x_m)*1e6:.2f} cm³", "ok"),
            ("Volumen", f"Vs={model.swept_volume_m3*1e6:.2f} cm³", f"V_cyl={model.volume_m3(x_m)*1e6:.2f} cm³", "ok"),
        ]
        for slot in [model.transfer, model.exhaust]:
            if slot is None:
                continue
            open_h = slot.open_height_m(dist)
            rows.append((
                slot.name,
                f"open@{slot.opens_at_m()*1000:.1f}, full@{slot.fully_open_at_m()*1000:.1f} mm",
                f"h_open={open_h*1000:.2f} mm, A={slot.area_geom_m2(dist)*1e6:.2f} mm²",
                "offen" if open_h > 0 else "geschlossen",
            ))
        self.summary_table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                self.summary_table.setItem(r, c, QTableWidgetItem(str(val)))
        self.summary_table.resizeColumnsToContents()

    def refresh_plots(self) -> None:
        model = self.model
        total_mm = model.stroke_m * 1000.0
        xs = [i * total_mm / 200.0 for i in range(201)]
        slot_y = [model.transfer.open_height_m(x / 1000.0) * 1000.0 if model.transfer else 0.0 for x in xs]
        current_dist_mm = model.distance_from_tdc_m(self.current_x_m) * 1000.0
        current_slot = model.transfer.open_height_m(model.distance_from_tdc_m(self.current_x_m)) * 1000.0 if model.transfer else 0.0
        self.plot_slot.plot_curve(xs, slot_y, "open_h Transfer [mm]", current_dist_mm, current_slot, "#38bdf8")
        vol_y = [ (model.clearance_volume_m3 + model.piston_area_m2 * (x/1000.0)) * 1e6 for x in xs]
        current_vol = model.volume_m3(self.current_x_m) * 1e6
        self.plot_vol.plot_curve(xs, vol_y, "V_cyl [cm³]", current_dist_mm, current_vol, "#f59e0b")

    def refresh_formula_text(self) -> None:
        m = self.model
        x = self.current_x_m
        d = m.distance_from_tdc_m(x)
        tr = m.transfer
        ex = m.exhaust
        lines = [
            "CONFIG -> MODELL -> PHYSIK",
            "",
            f"1) TDC-Definition: TDC = x_max = {m.x_max_m*1000:.1f} mm",
            f"2) BDC-Definition: BDC = x_min = {m.x_min_m*1000:.1f} mm",
            f"3) Hub: stroke = x_max - x_min = {m.stroke_m*1000:.1f} mm",
            f"4) Kolbenfläche: A_piston = pi/4 * D² = pi/4 * {m.piston_diameter_m:.6f}² = {m.piston_area_m2:.6g} m²",
            f"5) Verdichtungsverhältnis: CR = {m.compression_ratio:.6g}",
            f"6) Hubvolumen: Vs = A_piston * stroke = {m.piston_area_m2:.6g} * {m.stroke_m:.6g} = {m.swept_volume_m3:.6g} m³",
            f"7) Restvolumen: Vc = Vs / (CR - 1) = {m.swept_volume_m3:.6g} / ({m.compression_ratio:.6g} - 1) = {m.clearance_volume_m3:.6g} m³",
            f"8) Abstand von TDC: distance_from_tdc = x_max - x = {m.x_max_m:.6f} - ({x:.6f}) = {d:.6f} m",
            f"9) Zylindervolumen: V_cyl = Vc + A_piston * distance_from_tdc = {m.clearance_volume_m3:.6g} + {m.piston_area_m2:.6g} * {d:.6g}",
            f"   -> V_cyl = {m.volume_m3(x)*1e6:.3f} cm³",
            f"10) Bounce-Querschnitt: A_geom = pi/4 * D_bounce² = pi/4 * {m.bounce_diameter_m:.6f}² = {m.bounce_chamber_cross_section_m2:.6g} m²",
            f"11) Bounce-Hubvolumen: Vh_b = A_geom * Lh_b = {m.bounce_chamber_cross_section_m2:.6g} * {m.bounce_length_m:.6g} = {m.bounce_swept_volume_m3:.6g} m³",
            f"12) Bounce-Verdichtungsverhältnis: CR_b = {m.bounce_compression_ratio:.6g}",
            f"13) Bounce-Minimalvolumen bei UT: Vb_min = Vh_b / (CR_b - 1) = {m.bounce_swept_volume_m3:.6g} / ({m.bounce_compression_ratio:.6g} - 1) = {m.bounce_volume_min_m3:.6g} m³",
            f"14) Bounce-Maximalvolumen bei OT: Vb_max = Vb_min + Vh_b = {m.bounce_volume_min_m3:.6g} + {m.bounce_swept_volume_m3:.6g} = {m.bounce_volume0_m3:.6g} m³",
            f"15) Wirksame Bounce-Fläche über den Freikolbenhub: A_eff = Vh_b / stroke = {m.bounce_swept_volume_m3:.6g} / {m.stroke_m:.6g} = {m.bounce_area_m2:.6g} m²",
            f"16) Aktuelles Bounce-Volumen: Vb = Vb_max - A_eff * (x - x_min) = {m.bounce_volume0_m3:.6g} - {m.bounce_area_m2:.6g} * ({x:.6f} - {m.x_min_m:.6f})",
            f"   -> Vb = {m.bounce_volume_m3(x):.6g} m³ = {m.bounce_volume_m3(x)*1e6:.3f} cm³",
            "",
        ]
        if tr:
            lines += [
                "TRANSFER-SLOT",
                f"distance_from_tdc_m = {tr.distance_from_tdc_m:.6f} m",
                f"height_m            = {tr.height_m:.6f} m",
                f"width_m             = {tr.width_m:.6f} m",
                f"count               = {tr.count}",
                f"open_h = clamp(distance_from_tdc - slot_distance, 0, slot_height)",
                f"      = clamp({d:.6f} - {tr.distance_from_tdc_m:.6f}, 0, {tr.height_m:.6f})",
                f"      = {tr.open_height_m(d):.6f} m = {tr.open_height_m(d)*1000:.3f} mm",
                f"A_geom = n * width * open_h = {tr.count} * {tr.width_m:.6f} * {tr.open_height_m(d):.6f}",
                f"      = {tr.area_geom_m2(d):.6f} m² = {tr.area_geom_m2(d)*1e6:.3f} mm²",
                "",
            ]
        if ex:
            lines += [
                "AUSLASS-SLOT",
                f"distance_from_tdc_m = {ex.distance_from_tdc_m:.6f} m",
                f"height_m            = {ex.height_m:.6f} m",
                f"width_m             = {ex.width_m:.6f} m",
                f"count               = {ex.count}",
                f"open_h = clamp(distance_from_tdc - slot_distance, 0, slot_height)",
                f"      = clamp({d:.6f} - {ex.distance_from_tdc_m:.6f}, 0, {ex.height_m:.6f})",
                f"      = {ex.open_height_m(d):.6f} m = {ex.open_height_m(d)*1000:.3f} mm",
                f"A_geom = n * width * open_h = {ex.count} * {ex.width_m:.6f} * {ex.open_height_m(d):.6f}",
                f"      = {ex.area_geom_m2(d):.6f} m² = {ex.area_geom_m2(d)*1e6:.3f} mm²",
            ]
        self.formula_text.setPlainText("\n".join(lines))

    def on_open_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Config laden", "", "YAML (*.yaml *.yml);;Alle Dateien (*)")
        if path:
            self.load_config(Path(path))

    def load_config(self, path: Path) -> None:
        if yaml is None:
            QMessageBox.critical(self, APP_TITLE, "PyYAML ist nicht verfügbar.")
            return
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            self.apply_config_dict(data)
            self.current_config_path = path.resolve()
            self.settings.setValue('files/last_config_path', str(self.current_config_path))
            self._update_statusbar_fields()
            self.statusBar().showMessage(f"Config geladen: {path}")
        except Exception as exc:
            QMessageBox.critical(self, APP_TITLE, f"Config konnte nicht geladen werden:\n{exc}")

    def apply_config_dict(self, data: dict[str, Any]) -> None:
        fp = (((data or {}).get("free_piston") or {}).get("mechanics") or {})
        self.x_min.setValue(float(fp.get("x_min_m", -0.04)) * 1000.0)
        self.x_max.setValue(float(fp.get("x_max_m", 0.04)) * 1000.0)
        piston_diameter_m = fp.get("piston_diameter_m")
        compression_ratio = fp.get("compression_ratio")
        if piston_diameter_m is None:
            piston_area_m2 = float(fp.get("piston_area_m2", 0.00436))
            piston_diameter_m = math.sqrt(4.0 * piston_area_m2 / math.pi)
        if compression_ratio is None:
            piston_area_m2 = float(fp.get("piston_area_m2", 0.00436))
            clearance_volume_m3 = float(fp.get("clearance_volume_m3", 2.5e-05))
            swept_volume_m3 = piston_area_m2 * max(float(fp.get("x_max_m", 0.04)) - float(fp.get("x_min_m", -0.04)), 1.0e-12)
            compression_ratio = (swept_volume_m3 + clearance_volume_m3) / max(clearance_volume_m3, 1.0e-12)
        self.piston_diameter.setValue(float(piston_diameter_m) * 1000.0)
        self.compression_ratio.setValue(float(compression_ratio))
        volumes = (((data or {}).get("preprocessing") or {}).get("volumes") or [])
        bounce = next((v for v in volumes if isinstance(v, dict) and v.get("type") == "bounce_chamber"), None)
        if bounce is None:
            bounce = (((data or {}).get("free_piston") or {}).get("bounce") or {})
        bounce_diameter_m = bounce.get("chamber_diameter_m")
        bounce_length_m = bounce.get("chamber_length_m")
        bounce_cr = bounce.get("compression_ratio")
        if bounce_diameter_m is None or bounce_length_m is None or bounce_cr is None:
            fallback_vmax_m3 = float(bounce.get("chamber_volume0_m3", 3.0e-04))
            bounce_diameter_m = float(piston_diameter_m)
            bounce_area_m2 = 0.25 * math.pi * float(bounce_diameter_m) * float(bounce_diameter_m)
            stroke_m = max(float(fp.get("x_max_m", 0.04)) - float(fp.get("x_min_m", -0.04)), 1.0e-12)
            swept_m3 = bounce_area_m2 * stroke_m
            bounce_length_m = stroke_m
            if fallback_vmax_m3 <= swept_m3:
                bounce_cr = 2.0
            else:
                bounce_cr = fallback_vmax_m3 / max(fallback_vmax_m3 - swept_m3, 1.0e-12)
        self.bounce_diameter.setValue(float(bounce_diameter_m) * 1000.0)
        self.bounce_length.setValue(float(bounce_length_m) * 1000.0)
        self.bounce_compression_ratio.setValue(float(bounce_cr))
        conns = (((data or {}).get("preprocessing") or {}).get("connections") or [])
        tr = self._find_slot(conns, "transfer_slot")
        ex = self._find_slot(conns, "exhaust_slot")
        if tr:
            self.tr_dist.setValue(float(tr.get("distance_from_tdc_m", 0.055)) * 1000.0)
            self.tr_h.setValue(float(tr.get("height_m", 0.012)) * 1000.0)
            self.tr_w.setValue(float(tr.get("width_m", 0.020)) * 1000.0)
            self.tr_n.setValue(float(tr.get("number_of_identical_holes", 2)))
        if ex:
            self.ex_dist.setValue(float(ex.get("distance_from_tdc_m", 0.045)) * 1000.0)
            self.ex_h.setValue(float(ex.get("height_m", 0.014)) * 1000.0)
            self.ex_w.setValue(float(ex.get("width_m", 0.024)) * 1000.0)
            self.ex_n.setValue(float(ex.get("number_of_identical_holes", 2)))
        # start x from initial conditions if present
        init = (((data or {}).get("free_piston") or {}).get("initial_conditions") or {})
        if "x0_m" in init:
            self.current_x.setValue(float(init["x0_m"]) * 1000.0)
        self.refresh_all()

    @staticmethod
    def _find_slot(conns: list[Any], name: str) -> Optional[dict[str, Any]]:
        for c in conns:
            if isinstance(c, dict) and c.get("name") == name:
                return c
        return None

    def on_save_report(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Diagnosebericht speichern", "fp_diagnose.txt", "Text (*.txt)")
        if not path:
            return
        Path(path).write_text(self.formula_text.toPlainText(), encoding="utf-8")
        self.statusBar().showMessage(f"Diagnosebericht gespeichert: {path}")


def _get_or_create_qapplication(argv: list[str]) -> tuple[QApplication, bool]:
    existing_app = QApplication.instance()
    if existing_app is not None:
        return existing_app, False
    try:
        return QApplication(argv), True
    except RuntimeError:
        existing_app = QApplication.instance()
        if existing_app is None:
            raise
        return existing_app, False


def main(argv: list[str]) -> int:
    app, created_app = _get_or_create_qapplication(argv)
    app.setOrganizationName(APP_ORG)
    app.setApplicationName(APP_NAME)
    cfg = argv[1] if len(argv) > 1 else None
    win = FreePistonGeometryEditor(cfg)
    # keep a reference on the application object so the window is not collected
    windows = getattr(app, "_fp_geometry_windows", None)
    if windows is None:
        windows = []
        setattr(app, "_fp_geometry_windows", windows)
    windows.append(win)
    show_foreground(win)
    if not created_app:
        return 0
    return app.exec()


if __name__ == "__main__":
    main(sys.argv)
